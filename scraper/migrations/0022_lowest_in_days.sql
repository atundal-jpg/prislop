-- 0022_lowest_in_days.sql
--
-- Prisjakt-modellen: «laveste pris på N dager». Ny kolonne i
-- v_prislop_products:
--
--   lowest_in_days  int  Lengden (i dager, inkl. i dag) på det bakoverliggende
--                        vinduet der dagens laveste pris er lik eller under
--                        ALT vi har observert. Konkret: dager siden siste dag
--                        i den interne produktnivå-minserien (drop14_daily,
--                        0019/0020) med pris STRENGT UNDER dagens — eller
--                        hele seriens lengde + 1 hvis ingen lavere pris noen
--                        gang er observert. NULL uten historikk.
--
-- Semantikk og disiplin:
-- - «Dagens pris» er nøyaktig from_price sitt filter (drop14_today_all:
--   ferske, on-lager). Serien er drop14_daily: daglig produktnivå-MIN,
--   lagerfiltrert når kjent, LEAD()-fremoverfylt til butikkens siste
--   bekreftede dag — samme fundament som drop14, IKKE det offentlige
--   v_prislop_price_series.
-- - PÅSTANDEN KAN ALDRI OVERSTIGE FAKTISK DEKNING: serien starter ved
--   første observasjon, så et produkt sporet i 12 dager kan maksimalt få
--   lowest_in_days = 13. Katalogen ble re-splittet 5./9. juli — tallene
--   vokser av seg selv utover august/september. Frontend viser teksten
--   først ved >= 30 dager (LOWEST_MIN_DAYS i index.html) OG kun når
--   sparklinen selv bekrefter «på laveste nå» — de to skal aldri sprike.
--   Observasjonsvinduet i drop14_obs (104 dager) er dermed også taket.
-- - Prislik regnes som «fortsatt lavest» (strengt mindre-enn i filteret):
--   en pris som tangerer bunnen bryter ikke rekka.
-- - Erstatter IKKE drop14 (falt nylig, mot egen basislinje) og ikke
--   deal_gap (billigere enn de andre butikkene NÅ) — tredje, ortogonal
--   dimensjon: hvor lenge dagens pris har vært bunnen.
--
-- drop14, discount, from_price, rank_score og deal_gap/deal_store (0021) er
-- UENDRET; hele viewet gjenskapes kun fordi CREATE OR REPLACE VIEW krever
-- full definisjon. Grunnteksten er identisk med 0021. v_prislop_price_series
-- er uendret. Regel 5-sjekker (EXPLAIN ANALYZE + dublett) kjøres før prod.

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
  -- av discount (uendret siden 0016/0019).
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

-- ================= godt kjøp: kryss-butikk-avstand (0021) =================
deal_store_min as (
  -- Laveste ferske on-lager-pris per butikk per produkt — nøyaktig samme
  -- filter som from_price, bare uten å kollapse på tvers av butikker.
  select
    fo.product_id,
    fo.store_id,
    min(fo.current_price) filter (where coalesce(fo.in_stock, true)) as p
  from fresh_offers fo
  group by fo.product_id, fo.store_id
),
deal_best as (
  -- Billigste butikk. Ved prislik deles «best» vilkårlig men deterministisk
  -- (store_id som tiebreak); taperen havner blant «de andre» og drar
  -- medianen NED — konservativt, aldri et falskt flagg.
  select distinct on (product_id) product_id, store_id as best_store, p as best_price
  from deal_store_min
  where p is not null
  order by product_id, p asc, store_id
),
deal_others as (
  select
    b.product_id,
    b.best_store,
    b.best_price,
    (percentile_cont(0.5) within group (order by s.p))::numeric as med_others,
    count(*) as n_others
  from deal_best b
  join deal_store_min s
    on s.product_id = b.product_id
   and s.store_id <> b.best_store
   and s.p is not null
  group by b.product_id, b.best_store, b.best_price
),
deal_cheapest_offer as (
  -- Det konkrete tilbudet som setter prisen (krav 3 måles på DETTE, ikke på
  -- butikkens samlede lager). id som tiebreak ved prislike tilbud.
  select distinct on (fo.product_id) fo.product_id, fo.id as offer_id
  from fresh_offers fo
  join deal_best b on b.product_id = fo.product_id and b.best_store = fo.store_id
  where coalesce(fo.in_stock, true) and fo.current_price is not null
  order by fo.product_id, fo.current_price asc, fo.id
),
deal as (
  select
    o.product_id,
    round(1 - o.best_price / nullif(o.med_others, 0), 3) as deal_gap,
    st.name as deal_store
  from deal_others o
  join deal_cheapest_offer co on co.product_id = o.product_id
  join prislop.stores st on st.id = o.best_store
  left join sz s on s.offer_id = co.offer_id
  where o.n_others >= 2                        -- (1) minst 3 butikker totalt
    and o.best_price <= o.med_others * 0.75    -- (2) minst 25 % under medianen
    and coalesce(s.n_in, 0) >= 3               -- (3) minst 3 størrelser på lager
),
-- ================= /godt kjøp =================

-- ===================== drop14: robust, produktnivå ======================
offer_first_seen as (
  select offer_id, min((observed_at at time zone 'Europe/Oslo')::date) as first_day
  from prislop.price_history
  group by offer_id
),
drop14_obs as (
  -- Historisk daglig MIN per butikk (0018-prinsippet), lagerfiltrert når
  -- kjent. INGEN etablert-filter her — basislinjen og (d)-fallbacken (se
  -- 0019) skal reflektere den fulle, ærlige historikken.
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
drop14_store_last_seen as (
  select
    va.product_id,
    ofr.store_id,
    max((ofr.last_seen_at at time zone 'Europe/Oslo')::date) as last_seen_day
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  group by va.product_id, ofr.store_id
),
drop14_intervals as (
  -- Samme LEAD()-teknikk som v_prislop_price_series (0020) — se den
  -- migrasjonskommentaren for hvorfor. Erstatter 0019 sin korrelerte
  -- subquery per dag, som tok 8s og felte nettsiden.
  select
    o.product_id,
    o.store_id,
    o.price,
    o.day as start_day,
    coalesce(
      lead(o.day) over (partition by o.product_id, o.store_id order by o.day) - 1,
      sls.last_seen_day
    ) as end_day
  from drop14_obs o
  join drop14_store_last_seen sls
    on sls.product_id = o.product_id and sls.store_id = o.store_id
),
drop14_daily as (
  -- Daglig minpris, produktnivå, kjent-lager-filtrert. IKKE det offentlige
  -- v_prislop_price_series (som bevisst mangler debut-vakten, se 0019) —
  -- en egen serie kun til bruk i drop14 (og lowest_in_days, 0022).
  select
    product_id,
    gs::date as day,
    min(price) as min_price
  from drop14_intervals,
  lateral generate_series(
    start_day::timestamptz,
    greatest(end_day, start_day)::timestamptz,
    interval '1 day'
  ) gs
  where end_day >= start_day
  group by product_id, gs::date
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
  -- når vi står i (d)-fallback (se 0019): ingen moden basislinje å
  -- beskytte, så "i dag" skal være den ærlige, fulle prisen.
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
  -- Samme filter, PLUSS krav om at TILBUDET selv har vært sporet siden
  -- minst like lenge som basislinjens egen eldste bidragsdag
  -- (window_first_day) — se 0019 punkt (e) for full begrunnelse (debut-
  -- vakt, uendret av denne migrasjonen).
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

-- ============ lowest_in_days: «laveste pris på N dager» (0022) ============
lowest_since as (
  -- Siste dag med pris STRENGT UNDER dagens (og seriens første dag) i den
  -- interne minserien. Dagens pris = drop14_today_all (from_price-filteret).
  -- day < i dag: drop14_daily fremover-fyller til butikkens siste bekreftede
  -- dag, som for aktive butikker ER i dag — en SYNTETISK i-dag-rad (gårsdagens
  -- pris) som ikke skal kunne sette last_lower_day. «I dag» representeres
  -- utelukkende av den live today_price. (drop14 er upåvirket av dette:
  -- basislinjevinduet slutter uansett ved -7.)
  select
    t.product_id,
    max(d.day) filter (where d.min_price < t.today_price) as last_lower_day,
    min(d.day) as first_day
  from drop14_today_all t
  join drop14_daily d on d.product_id = t.product_id
  where d.day < (now() at time zone 'Europe/Oslo')::date
  group by t.product_id, t.today_price
),
-- ==================== /lowest_in_days ====================

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
  agg.product_id, brand, model, gender, product_line, category,
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
  subcategory, carbon_plate, waterproof, wide,
  d.deal_gap, d.deal_store,
  case
    when ls.product_id is null then null
    when ls.last_lower_day is not null
      then ((now() at time zone 'Europe/Oslo')::date - ls.last_lower_day)
    else ((now() at time zone 'Europe/Oslo')::date - ls.first_day) + 1
  end as lowest_in_days
from agg
left join deal d on d.product_id = agg.product_id
left join lowest_since ls on ls.product_id = agg.product_id;

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14 er produktnivå-MIN mot MEDIAN-basislinje i vinduet [-21,-7] dager (0019), beregnet med LEAD()-vindusfunksjon (0020). Lagerfiltrert når kjent, debut-vakt, fallback for unge produkter, ingen cap; fall >50% flagges i post_harvest_check.py. discount uendret siden 0016. deal_gap/deal_store (0021): «godt kjøp»-flagg når billigste butikk ligger >=25% under medianen av de andre butikkenes laveste pris, minst 3 butikker og minst 3 størrelser på lager i det billigste tilbudet; NULL ellers — skjev konsentrasjon ADVARES i post_harvest_check.py. lowest_in_days (0022): antall dager (inkl. i dag) dagens pris har vært laveste observerte i den interne minserien; kan aldri overstige faktisk sporet historikk; frontend viser først ved >=30 dager og kun sammen med sparklinens «på laveste nå».';

grant select on public.v_prislop_products to anon, authenticated;
