-- 0018_price_series_robust_daily_min.sql
--
-- OPPGAVE 1/3 (fundament for 0019): v_prislop_price_series er kilden både
-- sparklinen og (fra 0019) drop14 leser fra. Den hadde FIRE uavhengige
-- unøyaktigheter, alle oppdaget ved å sammenligne en korrekt "i dag"-pris mot
-- viewets egen historikk (BUG 4 lagt til etter at PR-en med BUG 1-3 var
-- merget og live — se commit-historikk):
--
-- BUG 1 — vilkårlig plukk blant fargevarianter, ikke laveste pris:
-- `obs`-CTE-en (uendret siden 0006) grupperer per BUTIKK per dag og plukket
-- «sist observerte pris» med
-- `(array_agg(ph.price order by ph.observed_at desc))[1]`. Når en butikk har
-- FLERE tilbud (fargevarianter) for samme produkt logget på samme tidspunkt —
-- normalt, siden én scrape-runde skriver alt fra butikken i samme transaksjon
-- — er rekkefølgen mellom like tidsstempler ikke garantert av SQL, så hvilken
-- farges pris som "vinner" er tilfeldig. Funnet: 400 butikk-produkt-dag-
-- kombinasjoner i historikken har flere ulike priser på nøyaktig samme
-- tidspunkt. Konkret: Adidas Adistar 2 herre hos Sport 1 har to fargevarianter
-- til flate 499 og 1499 kr, ALDRI endret — men den gamle logikken kunne plukke
-- 1499 som "butikkens pris" en dag og 499 en annen, og se ut som et 67 %-fall
-- uten at noe faktisk endret seg. FIKS: `min(ph.price)` per butikk per dag i
-- stedet — svarer på "billigste tilgjengelige farge/størrelse hos denne
-- butikken", som er nøyaktig det sparklinen allerede er merket med
-- ("Laveste pris på tvers av farger og størrelser").
--
-- BUG 2 — ingen lagerfiltrering, heller ikke for dagens rad: et utsolgt tilbud
-- med en gammel pris som ikke har endret seg siden det gikk tomt, kunne sette
-- BÅDE historiske dager og dagens rad. Konkret: Asics Fuji Lite 5 herre —
-- Bull Ski & Kajakk sto utsolgt til 800 kr (siste pris 10. juli, aldri
-- endret siden), mens Löplabbet har skoen på lager til 1600 kr flatt hele
-- perioden. Uten fiks ville både sparkline og (fra 0019) drop14-badge vist et
-- fall på ~50 % basert på en pris ingen butikk faktisk tilbyr — samme
-- feilmønster («pris vi ikke kan tilby») som resten av denne saken retter opp,
-- bare via "utsolgt tilbud" i stedet for "feil butikk". FIKS, todelt:
--   - Historiske dager: nå som 0017 finnes, brukes price_history.in_stock når
--     kjent (`filter (where coalesce(ph.in_stock, true))` i `obs`) — NULL
--     (all historikk før 0017, eller ukjent) telles som tilgjengelig/listepris,
--     ALDRI som utsolgt, jf. 0017-kommentaren. Vi har ingen historisk
--     lagerstatus for perioden før 0017, så vi kan ikke filtrere det vi ikke
--     vet — men fra og med 0017 vokser dekningen automatisk etter hvert som
--     prisendringer logges.
--   - Dagens rad: beregnes IKKE via fremover-fylling av price_history i det
--     hele tatt (som ville hatt samme mangel — ingen historisk lagerstatus å
--     stole på for tidligere dager, men DAGENS lagerstatus er alltid kjent).
--     Hentes i stedet direkte fra prislop.offers, filtrert på nøyaktig samme
--     regel som from_price i v_prislop_products (0014): ferske tilbud
--     (last_seen_at < 2 dager) OG coalesce(in_stock, true). Dette er alltid
--     den mest oppdaterte, kjøpbare prisen vi har.
--
-- BUG 3 — dagsgrense i UTC, ikke norsk tid: `observed_at::date` og
-- `current_date` bruker sesjonens tidssone (UTC på Supabase), så "i dag" og
-- "for 14 dager siden" kan forskyves en time eller to i forhold til faktisk
-- norsk døgn, avhengig av klokkeslett for scrapen. FIKS: all dags-bøtting og
-- "i dag"-referanse regnes nå eksplisitt i Europe/Oslo
-- (`(x at time zone 'Europe/Oslo')::date`).
--
-- BUG 4 — fremover-fyllingsvinduet (14 dager) forveksler "prisen endret seg
-- nylig" med "butikken finnes fortsatt". Oppdaget live på prisløp.no etter at
-- BUG 1-3 var deployet: Asics Gel-FujiSetsu 3 GTX herre viste en sparkline
-- som klatret 999 → 1260 → 2100 kr over tre dager, etterfulgt av et komplett
-- opphold (ingen data helt fram til i dag). Årsak: Intersport (999 kr),
-- Torshov (1260 kr) og XXL (1749 kr) har ALLE kun logget prisen sin ÉN gang
-- (hhv. 15., 16. og 15./16. juni) — prisen har aldri endret seg siden, men
-- butikkene har vært aktivt sporet (offers.last_seen_at) hver 6. time helt
-- fram til i dag. Det gamle fremover-fyllingsvinduet («siste kjente pris,
-- maks 14 dager tilbake fra DEN DAGEN») lot likevel Intersports 999-rad gå ut
-- på dato 14 dager etter 15. juni og falle ut av MIN-beregningen — deretter
-- Torshov, deretter XXL — slik at kun den DYRESTE, sist observerte butikken
-- (Sport 1, 2100 kr, logget 19. juni) stod igjen lengst. Resultatet: en
-- serie som ser ut som et stigende prisløp, når realiteten er at fire
-- butikker har ligget knirkefast flate priser hele perioden. Dette er
-- nøyaktig "død-butikk-henger-igjen"-svakheten CLAUDE.md/saksbeskrivelsen
-- pekte på (jf. Get Inspired) — bare i motsatt retning: en AKTIV, bekreftet
-- butikk mistet dekning for tidlig fordi vinduet måler feil ting.
--
-- Kjernefeilen: 14-dagersvinduet er ankret til `price_history.observed_at`
-- (når prisen sist ENDRET seg), men burde vært ankret til
-- `offers.last_seen_at` (når vi sist BEKREFTET at tilbudet fortsatt finnes).
-- Disse er ikke det samme — en pris kan stå urørt i måneder mens butikken
-- likevel skrapes hver 6. time. FIKS: fremover-fylling er nå ubegrenset
-- bakover i tid (finner alltid siste kjente pris, uansett alder), men
-- begrenset FORTSATT av en ny `store_last_seen`-sperre: et butikk-produkt-par
-- fremover-fylles kun for dager til og med siste dag vi faktisk så det paret
-- (`max(offers.last_seen_at)`, uansett om prisen endret seg da). En butikk
-- som slutter å bli skrapet (genuint død, à la Get Inspired) faller dermed
-- fortsatt ut av bildet nøyaktig når vi sist bekreftet den — det er BUG 4 sin
-- fiks som beholder riktig oppførsel for det tilfellet, samtidig som en
-- fortsatt-aktiv, bare-prisstabil butikk ikke lenger mister dekning etter 14
-- dager.
--
-- Uendret: 90-dagers eksponeringsvindu, "Lavest i perioden"-teksten og
-- SPARK_MIN_POINTS i index.html.
--
-- IKKE løst her, bevisst — se 0019-kommentaren: "debut-vakt" (ny butikk/
-- fargevariant som dukker opp midt i et sammenligningsvindu) rører kun
-- drop14-beregningen i v_prislop_products, ikke dette viewet. Sparklinens
-- RÅ historiske linje skal fortsatt vise den faktiske, ærlige laveste sporte
-- prisen hver dag — inkludert et legitimt hopp ned den dagen en ny, billigere
-- butikk begynner å bli sporet. Det er drop14 (badgen, prisfall-lista,
-- rank_score) som trenger beskyttelse mot at ETT enkelt slikt hopp leses som
-- et prisfall; selve historikk-grafen skal ikke lyve om hva vi faktisk har
-- sporet.

create or replace view public.v_prislop_price_series as
with obs as (
  select product_id, store_id, day, price from (
    select
      v.product_id,
      o.store_id,
      (ph.observed_at at time zone 'Europe/Oslo')::date as day,
      min(ph.price) filter (where coalesce(ph.in_stock, true)) as price
    from prislop.price_history ph
    join prislop.offers o    on o.id = ph.offer_id
    join prislop.variants v  on v.id = o.variant_id
    where ph.observed_at > now() - interval '104 days'
      and ph.price is not null
      and (ph.observed_at at time zone 'Europe/Oslo')::date < (now() at time zone 'Europe/Oslo')::date
    group by v.product_id, o.store_id, (ph.observed_at at time zone 'Europe/Oslo')::date
  ) x
  where price is not null
),
store_last_seen as (
  -- Siste dag vi i det hele tatt bekreftet dette butikk-produkt-paret
  -- (offers.last_seen_at, uansett om prisen endret seg da). Styrer NÅR
  -- fremover-fyllingen skal slutte (BUG 4) — ikke hvor langt den kan strekke
  -- seg bakover, som nå er ubegrenset.
  select
    va.product_id,
    ofr.store_id,
    max((ofr.last_seen_at at time zone 'Europe/Oslo')::date) as last_seen_day
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  group by va.product_id, ofr.store_id
),
bounds as (
  select product_id, min(day) as first_day
  from obs
  group by product_id
),
days as (
  select b.product_id, gs::date as day
  from bounds b
  cross join lateral generate_series(
    b.first_day::timestamptz,
    ((now() at time zone 'Europe/Oslo')::date - 1)::timestamptz,
    interval '1 day'
  ) gs
),
pairs as (
  select distinct d.product_id, d.day, o.store_id
  from days d
  join obs o on o.product_id = d.product_id
),
filled as (
  select
    p.product_id,
    p.day,
    p.store_id,
    case when p.day <= sls.last_seen_day then (
      select o2.price
      from obs o2
      where o2.product_id = p.product_id
        and o2.store_id = p.store_id
        and o2.day <= p.day
      order by o2.day desc
      limit 1
    ) else null end as ff_price
  from pairs p
  left join store_last_seen sls
    on sls.product_id = p.product_id and sls.store_id = p.store_id
),
historical_days as (
  select
    product_id,
    day,
    min(ff_price) as min_price,
    count(ff_price) as n_stores
  from filled
  where ff_price is not null
  group by product_id, day
),
today_row as (
  -- Dagens laveste pris: samme regel som from_price i v_prislop_products
  -- (0014) — ferske, on-lager tilbud, live fra offers-tabellen. Ingen
  -- fremover-fylling, ingen fallback til gammel/utsolgt pris.
  select
    va.product_id,
    (now() at time zone 'Europe/Oslo')::date as day,
    min(ofr.current_price) as min_price,
    count(distinct ofr.store_id) as n_stores
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  where ofr.last_seen_at > now() - interval '2 days'
    and coalesce(ofr.in_stock, true)
  group by va.product_id
)
select product_id, day, min_price, n_stores
from historical_days
where day > (now() at time zone 'Europe/Oslo')::date - interval '90 days'
union all
select product_id, day, min_price, n_stores
from today_row
where min_price is not null;

comment on view public.v_prislop_price_series is 'Per produkt, per dag: laveste pris på tvers av butikker (siste 90 dager, Europe/Oslo-døgn). Historiske dager: fremover-fylt UBEGRENSET bakover i tid, men kun til og med butikkens siste bekreftede dag (offers.last_seen_at, 0018 BUG 4 — var et fast 14-dagers vindu fra siste prisendring, som lot en fortsatt-aktiv men prisstabil butikk falle ut for tidlig). MIN per butikk per dag (0018 BUG 1 — var et vilkårlig "sist observert"-plukk blant fargevarianter). Lagerfiltrert når kjent (price_history.in_stock, 0017; NULL = ukjent = telles som tilgjengelig). Dagens rad: live fra offers, alltid ferske on-lager-tilbud (0018 BUG 2 — samme regel som from_price), aldri fremover-fylt. Brukes av prishistorikk-sparklinen og som fundament for drop14 (0019).';

grant select on public.v_prislop_price_series to anon, authenticated;
