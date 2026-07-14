-- 0019_drop14_robust_median_baseline.sql
--
-- Forutsetter 0017 (price_history.in_stock/sizes_in_stock) og 0018
-- (v_prislop_price_series sin MIN-per-butikk-per-dag- og lager-fiks). Les
-- begge først.
--
-- OPPGAVE 2: definer drop14 på det vi faktisk viser, robust nok til å
-- publiseres uten tilsyn. To bekreftede, motsatte feilretninger fra samme
-- rotårsak (per-tilbuds MAX/enkeltpunkt i stedet for produktnivå-MIN/
-- vindu), sett 14. juli:
--
--   Adizero Adios Pro 4 (herre): badge viste ▼30 %, men billigste pris
--   (Torshov, 2099) har ligget flatt hele historikken — de 30 % tilhørte
--   Löplabbet (3000→2100), en butikk som ikke setter from_price. OVERDREV.
--
--   Endorphin Speed 5 (dame): badge viste ▼20 %, sparklinen viste ▼25 %,
--   basert på v_prislop_price_series' 2000→1500. Verifisert mot rå
--   butikkpriser under (b): den ekte basislinjen er 1875 (Torshov, flat hele
--   perioden — 2000 kom fra 0018-bug1, samme array_agg-tvetydighet som
--   Adistar-saken), så det RIKTIGE, etterprøvbare svaret er 1875→1500 = 20 %,
--   ikke 25 %. Saksbeskrivelsens forventede ≈0,25 er dermed selv et symptom
--   på den bugen — se PR-beskrivelsen for detaljer.
--
-- Begge er etterprøvbare for enhver bruker som sjekker butikkprisene — dette
-- er siden vi deler i løpemiljøet, tallet må tåle kontroll.
--
-- BESKYTTELSER:
--
-- (a) GRUNNLAG: daglig MIN-pris på tvers av butikker, produktnivå — samme
--     prinsipp som v_prislop_price_series (0018), beregnet i en egen intern
--     serie (drop14_daily under). Et fall kan aldri rapporteres fra et
--     tilbud som ikke setter from_price — "i dag"-siden av sammenligningen
--     bruker alltid nøyaktig from_price sitt filter (ferske, on-lager).
--
-- (b) KJØPBARHET: når price_history.in_stock er kjent (0017, ikke NULL),
--     telles kun tilbud som var på lager. NULL (all historikk før 0017)
--     behandles som "listepris". Dagens endepunkt er ALLTID lagerfiltrert,
--     live fra offers — samme prinsipp som "Lavest nå"-fiksen (0014).
--
-- (c) BASISLINJE — MEDIAN over [i dag −21, i dag −7], ikke ett punkt. Ett
--     dårlig datapunkt = et falskt 30 %-fall (Bull-fraktbanneret og
--     XXL-isSelected-bugen ga begge nøyaktig den signaturen).
--
-- (d) FOR LITE DATA: krever minst 3 distinkte dager i [-21,-7]-vinduet for å
--     stole på medianen. Færre → fallback til FØRSTE kjente pris i den
--     samme (ubeskyttede, se punkt e) daglige serien — men KUN hvis
--     produktet har minst 3 dager historikk totalt. Ellers drop14 = 0.
--
-- (e) DEBUT-VAKT — omfang justert etter uttesting mot ekte data:
--     Første design krevde at ETHVERT tilbud (eller hele produktet) måtte
--     ha vært sporet i 21+ dager for å telle med i det hele tatt. Testet mot
--     databasen viste dette at KUN 120-141 av 871 produkter ville fått noe
--     drop14 overhodet — ikke fordi butikker mangler, men fordi 709
--     produkter (568 + 141) fikk sin FØRSTE registrering 5./9. juli, i det
--     som ser ut som en katalog-bred re-split/gjenoppbygging (jf. "race
--     recovery"-migrasjonen 0008 og CLAUDE.md sine kjente feilsignaturer). Et
--     blankt 21-dagerskrav ville dermed tømt prisfall-sida i ukevis av
--     grunner som ikke har noe med reelle prisfall å gjøre.
--
--     Innsikt: debut-vaktens ENESTE jobb er å hindre at en NYLIG DEBUTERENDE
--     butikk/fargevariant korrumperer en ALLEREDE MODEN medianbasislinje
--     (punkt c). Har produktet IKKE en moden basislinje ennå (færre enn 3
--     dager i vinduet, altså (d)-fallback), finnes ingenting å korrumpere —
--     fallbacken sammenligner allerede mot produktets egen, fulle, ærlige
--     historikk, som naturlig reflekterer hvilke butikker som fantes da.
--
--     Derfor: debut-vakten aktiveres KUN når (c) sin medianbasislinje
--     faktisk brukes (window_days >= 3). I det tilfellet må "i dag"-prisen
--     komme fra et tilbud som selv har vært sporet siden minst like lenge
--     som basislinjens EGEN eldste bidragsdag (window_first_day) —
--     ANKRET PER TILBUD, ikke per produkt, og ANKRET MOT VINDUETS FAKTISKE
--     DEKNING, ikke et fast "21 dager tilbake i tid". Grunn: et produkt kan
--     ha window_days>=3 selv om det bare er ~9 dager gammelt totalt, fordi
--     vinduets SENESTE grense (i dag −7) ligger nærmere "nå" enn den
--     tidligste (i dag −21) — da har SAMTLIGE tilbud på produktet vært
--     sporet siden window_first_day (de startet jo samtidig), og skal ikke
--     sperres av et krav de aldri kunne nådd. Et fast 21-dagerskrav her
--     (uttestet og forkastet) ville blokkert "i dag"-siden fullstendig for
--     ethvert produkt yngre enn 21 dager, UANSETT om det hadde en gyldig
--     3-dagers basislinje — verre enn å ikke ha debut-vakt i det hele tatt.
--     Er det billigste tilbudet i dag likevel yngre enn window_first_day
--     (en reell debutant midt i en ellers moden måleperiode), faller vi
--     tilbake til billigste ETABLERTE tilbud i stedet. For produkter i
--     (d)-fallback brukes derimot samme ufiltrerte "i dag"-pris som
--     from_price — ingen ekstra krav.
--
--     MERK, eksplisitt avvik fra første forslag: et per-produkt-anker (bruk
--     produktets eldste kjente tilbud som terskel for ALLE dets tilbud) ble
--     vurdert og forkastet — det løser 709-produkter-problemet likt, men
--     ville samtidig latt en helt ny butikk (Løpeshop/Boozt/Outnorth) sette
--     "i dag"-prisen for et ELLERS modent produkt uten sperre, altså akkurat
--     scenarioet vakten skal hindre. Ved å skille de to fallbackene (c vs d)
--     unngår vi det: modne produkter beholder fullt per-tilbuds vern, unge
--     produkter (som uansett ikke har noe modent å beskytte) slipper å
--     vente 21 dager.
--
--     Aktuelt snart: Løpeshop/Boozt/Outnorth kobles på. For produkter som
--     ALLEREDE er modne (har en median-basislinje) beskytter dette fullt ut.
--     Tilsvarende for produkt-sammenslåinger (jf. Mizuno-dedupen, 0007).
--
--     Bevisst IKKE lagt inn i v_prislop_price_series (0018) — sparklinens
--     RÅ historiske linje skal fortsatt vise den ærlige, faktisk sporte
--     laveste prisen hver dag. Det er PÅSTANDEN "dette er et prisfall"
--     (badge, prisfall-lista, rank_score) som trenger vakten.
--
-- (f) SANITY utenfor viewet: fall > 50 % caps IKKE lenger stille (sparklinen
--     har aldri hatt tak, se OPPGAVE 3). I stedet: egen vakt i
--     post_harvest_check.py (check_extreme_drop14) som feiler kjøringen og
--     lister berørte produkter — samme mønster som >80 %-identisk-pris-
--     vakten. Hos oss har 2 av 2 tidligere fall i denne størrelsen vært
--     bugger, ikke salg.
--
-- (g) discount (peak-basert) — VURDERT, IKKE ENDRET: samme type
--     kryss-butikk-avstand finnes (peak_price og current_price kommer alltid
--     fra SAMME tilbud, så ikke identisk med drop14-buggen, men MAX på
--     tvers av tilbud kan la et ANNET tilbud enn from_price avgjøre
--     prosenten). To legitime tolkninger mulig — "har prisen VI VISER falt
--     fra sin egen topp" (produktnivå-analog til ny drop14) vs. "er dette
--     beste pris NOEN butikk har hatt" (bevisst frikoblet fra from_price,
--     et oppdagelses-signal). Dette er en produktbeslutning, ikke en
--     teknisk fiks, og ingen akseptansetest dekker det — discount er derfor
--     UENDRET, samme per-tilbuds MAX-logikk som 0016. rank_score bruker
--     discount (vekt 2) og drop14 (vekt 3) — se PR-beskrivelsen for
--     før/etter-tall på rangeringseffekten av drop14-endringen alene.
--
-- TAK FJERNET fra selve drop14-tallet (se punkt f for hvorfor det er trygt):
-- ingen LEAST(..., 0.5) lenger.
--
-- from_price og discount er UENDRET av denne migrasjonen.

create or replace view public.v_prislop_products as
with fresh_offers as (
  select
    ofr.id,
    ofr.store_id,
    ofr.variant_id,
    ofr.current_price,
    ofr.in_stock,
    va.product_id,
    va.image_url
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  where ofr.last_seen_at > now() - interval '2 days'
),
hist as (
  -- peak_price: all-time høyeste registrerte pris for tilbudet. Brukes kun
  -- av discount (uendret, se (g) over).
  select
    fo.id as offer_id,
    (
      select max(ph.price)
      from prislop.price_history ph
      where ph.offer_id = fo.id
    ) as peak_price
  from fresh_offers fo
),
sz as (
  select
    os.offer_id,
    count(*) as n_all,
    count(*) filter (where os.in_stock) as n_in
  from prislop.offer_sizes os
  join fresh_offers fo on fo.id = os.offer_id
  group by os.offer_id
),

-- ===================== drop14: robust, produktnivå ======================
offer_first_seen as (
  select offer_id, min((observed_at at time zone 'Europe/Oslo')::date) as first_day
  from prislop.price_history
  group by offer_id
),
drop14_obs as (
  -- Historisk daglig MIN per butikk (0018-prinsippet), lagerfiltrert når
  -- kjent (punkt b). INGEN etablert-filter her — basislinjen og
  -- (d)-fallbacken skal reflektere den fulle, ærlige historikken. Se (e)
  -- for hvor debut-vakten faktisk sitter.
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
drop14_bounds as (
  select product_id, min(day) as first_day
  from drop14_obs
  group by product_id
),
drop14_days as (
  select b.product_id, gs::date as day
  from drop14_bounds b
  cross join lateral generate_series(
    b.first_day::timestamptz,
    ((now() at time zone 'Europe/Oslo')::date - 1)::timestamptz,
    interval '1 day'
  ) gs
),
drop14_pairs as (
  select distinct d.product_id, d.day, o.store_id
  from drop14_days d
  join drop14_obs o on o.product_id = d.product_id
),
drop14_filled as (
  select
    p.product_id, p.day, p.store_id,
    (
      select o2.price
      from drop14_obs o2
      where o2.product_id = p.product_id
        and o2.store_id = p.store_id
        and o2.day <= p.day
        and o2.day >  p.day - interval '14 days'
      order by o2.day desc
      limit 1
    ) as ff_price
  from drop14_pairs p
),
drop14_daily as (
  -- Daglig minpris, produktnivå, kjent-lager-filtrert. IKKE det offentlige
  -- v_prislop_price_series (som bevisst mangler debut-vakten, se 0018) —
  -- en egen serie kun til bruk i drop14.
  select product_id, day, min(ff_price) as min_price
  from drop14_filled
  where ff_price is not null
  group by product_id, day
),
drop14_baseline_window as (
  select
    product_id,
    percentile_cont(0.5) within group (order by min_price) as baseline_median,
    count(distinct day) as window_days,
    min(day) as window_first_day
  from drop14_daily
  where day >= (now() at time zone 'Europe/Oslo')::date - 21
    and day <= (now() at time zone 'Europe/Oslo')::date - 7
  group by product_id
),
drop14_earliest as (
  select distinct on (product_id) product_id, min_price as earliest_price
  from drop14_daily
  order by product_id, day asc
),
drop14_total_days as (
  select product_id, count(distinct day) as total_days
  from drop14_daily
  group by product_id
),
drop14_today_all as (
  -- "I dag", ufiltrert på alder — nøyaktig from_price sitt filter. Brukes
  -- når vi står i (d)-fallback: ingen moden basislinje å beskytte, så "i
  -- dag" skal være den ærlige, fulle prisen.
  select
    va.product_id,
    min(ofr.current_price) as today_price
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  where ofr.last_seen_at > now() - interval '2 days'
    and coalesce(ofr.in_stock, true)
  group by va.product_id
),
drop14_today_established as (
  -- Samme filter, PLUSS krav om at TILBUDET selv (ikke bare produktet) har
  -- vært sporet siden minst like lenge som basislinjens EGEN eldste
  -- bidragsdag (window_first_day) — IKKE et fast "21 dager tilbake i tid".
  -- Et 9 dager gammelt produkt kan ha window_days>=3 fordi vinduet
  -- [-21,-7] når inn i dets siste 2-3 sporte dager (today-7 er nærmere "i
  -- dag" enn today-21); da har SAMTLIGE dets tilbud vært sporet siden
  -- window_first_day (de startet jo samtidig), og skal ikke sperres av et
  -- vilkårlig 21-dagerskrav de aldri kunne nådd. Debut-vakten skal kun
  -- stoppe et tilbud som er YNGRE enn basislinjens egen dekning — ikke
  -- ethvert tilbud på et produkt som selv er ungt.
  select
    va.product_id,
    min(ofr.current_price) as today_price
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  join offer_first_seen ofs on ofs.offer_id = ofr.id
  join drop14_baseline_window bw on bw.product_id = va.product_id
  where ofr.last_seen_at > now() - interval '2 days'
    and coalesce(ofr.in_stock, true)
    and ofs.first_day <= bw.window_first_day
  group by va.product_id
),
drop14_calc as (
  select
    dtall.product_id,
    case when bw.window_days >= 3 then dte.today_price
         else dtall.today_price end as today_price,
    case
      when bw.window_days >= 3 then bw.baseline_median::numeric
      when td.total_days   >= 3 then ek.earliest_price
      else null
    end as baseline_price
  from drop14_today_all dtall
  left join drop14_today_established dte on dte.product_id = dtall.product_id
  left join drop14_baseline_window bw    on bw.product_id  = dtall.product_id
  left join drop14_total_days td         on td.product_id  = dtall.product_id
  left join drop14_earliest ek           on ek.product_id  = dtall.product_id
),
-- ==================== /drop14 ====================

base as (
  select
    pr.id as product_id,
    pr.brand,
    pr.model,
    pr.gender,
    pr.product_line,
    pr.category,
    pr.subcategory,
    pr.carbon_plate,
    pr.waterproof,
    pr.wide,
    min(fo.current_price) filter (where coalesce(fo.in_stock, true)) as from_price,
    count(distinct fo.store_id) as n_stores,
    count(distinct fo.variant_id) as n_colorways,
    coalesce(sum(s.n_in), 0)::bigint as sizes_in_stock,
    (array_agg(fo.image_url) filter (where fo.image_url is not null))[1] as image_url,
    round(coalesce(max(
      case when h.peak_price > fo.current_price
        then least((h.peak_price - fo.current_price) / nullif(h.peak_price, 0), 0.7)
        else null end
    ), 0), 3) as discount,
    round(
      case when coalesce(sum(s.n_all), 0) = 0 then 0
        else sum(s.n_in) / sum(s.n_all) end
    , 3) as stock_ratio
  from prislop.products pr
  join fresh_offers fo on fo.product_id = pr.id
  left join sz s   on s.offer_id = fo.id
  left join hist h on h.offer_id = fo.id
  group by pr.id, pr.brand, pr.model, pr.gender, pr.product_line, pr.category,
           pr.subcategory, pr.carbon_plate, pr.waterproof, pr.wide
),
agg as (
  select
    b.*,
    round(coalesce(
      case when dc.baseline_price > dc.today_price
        then (dc.baseline_price - dc.today_price) / nullif(dc.baseline_price, 0)
        else null end
    , 0), 6) as drop14
  from base b
  left join drop14_calc dc on dc.product_id = b.product_id
)
select
  product_id, brand, model, gender, product_line, category,
  from_price, n_stores, n_colorways, sizes_in_stock, image_url,
  discount, drop14, stock_ratio,
  round((
      2   * ln(1 + n_stores)
    + 1   * ln(1 + n_colorways)
    + 1.5 * stock_ratio
    + 2   * discount
    + 3   * drop14
    + case when sizes_in_stock < 5 then -2 else 0 end
  )::numeric, 3) as rank_score,
  subcategory, carbon_plate, waterproof, wide
from agg;

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14 (0019, forutsetter 0017+0018) er produktnivå-MIN mot MEDIAN-basislinje i vinduet [-21,-7] dager, lagerfiltrert når kjent, med debut-vakt (per tilbud, kun aktiv når en moden medianbasislinje finnes) mot nye butikker/fargevarianter, og fallback til først kjente pris for unge produkter (krever >=3 dager historikk totalt, ingen debut-vakt der). Ingen cap. Fall >50% flagges i post_harvest_check.py, ikke klippes. discount er uendret — se migrasjonskommentar for vurdering.';

grant select on public.v_prislop_products to anon, authenticated;
