-- 0016_drop14_product_level_min_price.sql
--
-- BUG: drop14 kunne rapportere et prisfall som den viste prisen aldri har
-- hatt. v_prislop_products beregnet drop14 PER TILBUD (h.base14 vs.
-- fo.current_price for samme tilbud) og tok så MAX på tvers av alle ferske
-- tilbud for produktet — mens from_price (prisen som faktisk vises) er MIN
-- på tvers av tilbudene. De to tallene kunne dermed komme fra hver sin
-- butikk. Eksempel 14. juli: Adizero Adios Pro 4 (herre) —
--
--   Torshov Sport   2099  — flat hele historikken → dette satte from_price
--   Löplabbet       2100  — falt fra 3000 → dette drev drop14 = 0.30
--   Intersport      2399  — flat
--   Sport 1         2999  — flat
--
-- Kortet viste «▼ 30 % siste 14 d» ved siden av «fra 2 099 kr», men de 2 099
-- kr har ikke falt — v_prislop_price_series (MIN per dag) bekrefter at
-- billigste pris har ligget flatt på 2099 fra 5.–14. juli. Fallet var ekte,
-- men tilhørte en butikk vi ikke viser prisen fra.
--
-- FIKS: drop14 beregnes nå PÅ PRODUKTNIVÅ, ikke per tilbud. Basislinjen
-- («prisen for 14 dager siden») er MIN på tvers av butikker av samme type
-- som from_price er MIN på tvers av butikker i dag — og begge er begrenset
-- til samme butikksett: ferske tilbud som er på lager nå (dvs. tilbudene som
-- faktisk setter from_price). Et tilbud som ikke setter from_price (fordi
-- det er utsolgt) kan dermed ikke lenger drive et rapportert fall — det var
-- nettopp Löplabbet-tilfellet over sin egen variant av dette (et tilbud som
-- ikke er den viste prisen, skal ikke kunne skape et fall for den viste
-- prisen). Per-tilbuds base14-beregningen (14-28-dagersvindu med fallback
-- til eldste kjente pris ved <14 dagers historikk, innført i 0005/0015) er
-- uendret — det som endres er at vi nå tar MIN av disse per-tilbuds
-- basisverdiene (blant on-lager-tilbud) i stedet for å sammenligne hvert
-- tilbud mot seg selv og ta MAX.
--
-- Verifisert mot casene i saken:
--   - Adizero Adios Pro 4, herre: baseline14 = MIN(2099, 3000, 2399, 2999)
--     blant on-lager-tilbud = 2099 = from_price → drop14 = 0. Riktig, siden
--     2099 (Torshov) har ligget flatt.
--   - Endorphin Speed 5, herre: eneste/billigste tilbud falt reelt
--     2499 → 1500 (10. juli), sporet fra 5. juli (fallback til eldste kjente
--     pris siden hele historikken er <14 dager) → baseline14 = 2499,
--     from_price = 1500 → drop14 = (2499-1500)/2499 ≈ 0,40. Uendret fra før,
--     siden dette allerede var et ekte, enkelt-butikk-tilfelle.
--
-- Strukturelt: aggregeringen er delt i to CTE-lag (base → agg) fordi Postgres
-- ikke lar en SELECT-liste referere til sine egne aliaser — drop14 trenger
-- from_price og den nye baseline14-kolonnen som ferdig-aggregerte verdier
-- fra et tidligere lag, ikke uttrykk beregnet i samme SELECT.
--
-- DISCOUNT (peak-basert) — VURDERT, IKKE ENDRET I DENNE MIGRASJONEN:
-- discount har en beslektet, men strukturelt litt annerledes, lekkasje: den
-- er fortsatt per-tilbud «riktig» i den forstand at peak_price og
-- current_price alltid kommer fra SAMME tilbud (aldri kryss-butikk som
-- drop14-buggen), men MAX på tvers av tilbud betyr at det tilbudet som har
-- falt mest fra sin egen historiske topp — ikke nødvendigvis butikken bak
-- from_price — avgjør hvilken discount-prosent som vises ved siden av
-- «fra»-prisen. Samme symptom som drop14-buggen (badge kan beskrive en pris
-- vi ikke viser), men riktig fiks er ikke like opplagt: et rent MIN-av-
-- per-tilbuds-peak (analogt med drop14 sin MIN-av-base14) ville gitt
-- baseline = laveste all-time-topp blant on-lager-tilbudene, som IKKE
-- nødvendigvis representerer «hvor høyt har PRODUKTETS billigste pris noen
-- gang vært» — riktig produktnivå-analog til drop14 sin nye logikk er
-- egentlig peak av price_series sin daglige MIN-pris (all-time-max av
-- billigste-på-tvers-av-butikker), som krever historikk over produktets
-- min-pris-serie, ikke bare per-tilbuds price_history. Det er en større
-- endring enn denne saken ber om, og ingen akseptansetest dekker det her —
-- så i tråd med CLAUDE.md/oppgavebeskrivelsen («ikke endre den stilltiende
-- hvis du er i tvil») lar jeg discount stå uendret og foreslår i stedet:
-- en oppfølgende migrasjon som definerer discount = (peak_of_daily_min -
-- from_price) / peak_of_daily_min, der peak_of_daily_min er
-- max(v_prislop_price_series.min_price) for produktet (evt. med et egnet
-- tidsvindu). rank_score bruker fortsatt discount som før inntil videre.

begin;

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
  -- peak_price: all-time høyeste registrerte pris for tilbudet (uendret).
  -- base14: pris 14-28 dager tilbake, med fallback til eldste kjente pris
  -- når hele historikken er kortere enn 14 dager (uendret fra 0005/0015).
  select
    fo.id as offer_id,
    (
      select max(ph.price)
      from prislop.price_history ph
      where ph.offer_id = fo.id
    ) as peak_price,
    coalesce(
      (
        select ph2.price
        from prislop.price_history ph2
        where ph2.offer_id = fo.id
          and ph2.observed_at <= now() - interval '14 days'
          and ph2.observed_at >  now() - interval '28 days'
        order by ph2.observed_at desc
        limit 1
      ),
      (
        select ph3.price
        from prislop.price_history ph3
        where ph3.offer_id = fo.id
          and not exists (
            select 1 from prislop.price_history ph4
            where ph4.offer_id = fo.id
              and ph4.observed_at <= now() - interval '14 days'
          )
        order by ph3.observed_at asc
        limit 1
      )
    ) as base14
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
    -- Produktnivå-baseline for drop14: MIN på tvers av on-lager-tilbud (samme
    -- butikksett og samme aggregeringsform — MIN — som from_price), IKKE MAX
    -- på tvers av alle tilbud. Et utsolgt tilbud (setter ikke from_price)
    -- teller ikke med her heller.
    min(h.base14) filter (where coalesce(fo.in_stock, true)) as base14_floor,
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
      case when b.base14_floor > b.from_price
        then least((b.base14_floor - b.from_price) / nullif(b.base14_floor, 0), 0.5)
        else null end
    , 0), 3) as drop14
  from base b
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

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14 fikset 14. juli (0016) til å sammenligne produktets viste pris (MIN on-lager-tilbud i dag) mot samme type basislinje 14 dager tilbake (MIN on-lager-tilbud), i stedet for å la et hvilket som helst tilbuds eget fall (MAX på tvers av tilbud) drive badgen uansett hvilken butikk from_price faktisk kommer fra. discount er uendret — se migrasjonskommentar for vurdering og forslag.';

grant select on public.v_prislop_products to anon, authenticated;

commit;
