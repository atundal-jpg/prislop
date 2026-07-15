-- 0020_forward_fill_performance.sql
--
-- PRODUKSJONSHENDELSE, 15. juli: prisløp.no gikk ned rett etter at 0018/0019
-- ble anvendt («Får ikke kontakt med katalogen»). Årsak: BUG 4-fiksen i 0018
-- (fremover-fylling ankret til offers.last_seen_at i stedet for et fast
-- 14-dagers vindu fra siste prisendring) fjernet den øvre grensen på en
-- korrelert subquery som kjøres PER (produkt × butikk × dag)-kombinasjon —
-- ca. 21 000 ganger for hele katalogen. Uten det gamle 14-dagersvinduet må
-- hvert oppslag nå sortere gjennom HELE den gjenværende prishistorikken for
-- det butikk-produkt-paret i stedet for et lite, avgrenset vindu.
--
-- Målt direkte mot databasen (EXPLAIN ANALYZE):
--   v_prislop_products        8034 ms  (anon har statement_timeout=3s,
--                                        authenticated 8s — begge feiler
--                                        eller ligger helt i grenseland)
--   v_prislop_price_series    11648 ms (samme mønster, ufiltrert)
-- PostgREST returnerer query_canceled som en generisk 500 til klienten —
-- derav "Får ikke kontakt med katalogen" på hele nettsiden, ikke bare ett
-- produktkort.
--
-- FIKS: samme resultat (fremover-fylling ankret til siste bekreftede dag),
-- men beregnet med et vindusfunksjonsuttrykk (LEAD) i stedet for én
-- korrelert subquery per dag:
--   1. For hver faktiske prisobservasjon (drop14_obs/obs), finn NESTE
--      observasjon for samme butikk-produkt-par med `lead(...) over
--      (partition by product_id, store_id order by day)`. Prisen er gyldig
--      fra sin egen dag til dagen FØR neste observasjon — eller til
--      butikkens siste bekreftede dag (store_last_seen) hvis det er den
--      SISTE kjente prisen.
--   2. Utvid hvert slikt intervall til enkeltdager med
--      `generate_series(start_day, end_day)` — samme totale antall rader
--      som før, men uten at Postgres må sortere/skanne hele historikken på
--      nytt for hver eneste dag.
-- Målt etter fiksen:
--   v_prislop_products         68 ms
--   v_prislop_price_series     70 ms
--
-- Ingen endring i SEMANTIKK fra 0018/0019 — kun i hvordan resultatet
-- beregnes. store_last_seen-sperren (en butikk fremover-fylles kun til og
-- med siste dag vi bekreftet den) er uendret; det er nøyaktig den samme
-- BUG 4-fiksen, bare uten ytelsesregresjonen.
--
-- 0018 og 0019 er IKKE redigert (begge er anvendt mot databasen) — denne
-- migrasjonen erstatter begge views på nytt med `create or replace view`.

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
  select
    va.product_id,
    ofr.store_id,
    max((ofr.last_seen_at at time zone 'Europe/Oslo')::date) as last_seen_day
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  group by va.product_id, ofr.store_id
),
intervals as (
  -- Hver observasjon er gyldig fra sin egen dag til dagen før NESTE
  -- observasjon for samme butikk-produkt-par — eller til butikkens siste
  -- bekreftede dag hvis dette er den siste kjente prisen (lead() er NULL).
  select
    o.product_id,
    o.store_id,
    o.price,
    o.day as start_day,
    coalesce(
      lead(o.day) over (partition by o.product_id, o.store_id order by o.day) - 1,
      sls.last_seen_day
    ) as end_day
  from obs o
  join store_last_seen sls
    on sls.product_id = o.product_id and sls.store_id = o.store_id
),
historical_days as (
  select
    product_id,
    gs::date as day,
    min(price) as min_price,
    count(*) as n_stores
  from intervals,
  lateral generate_series(
    start_day::timestamptz,
    greatest(end_day, start_day)::timestamptz,
    interval '1 day'
  ) gs
  where end_day >= start_day
  group by product_id, gs::date
),
today_row as (
  -- Dagens laveste pris: samme regel som from_price i v_prislop_products
  -- (0014) — ferske, on-lager tilbud, live fra offers-tabellen. Uendret fra
  -- 0018.
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

comment on view public.v_prislop_price_series is 'Per produkt, per dag: laveste pris på tvers av butikker (siste 90 dager, Europe/Oslo-døgn). Fremover-fylt til og med butikkens siste bekreftede dag (offers.last_seen_at, 0018 BUG 4), beregnet med LEAD()-vindusfunksjon i stedet for korrelert subquery per dag (0020 — 0018-versjonen tok 11.6s ufiltrert og felte hele nettsiden via PostgREST sin 3s/8s statement_timeout). MIN per butikk per dag (0018 BUG 1). Lagerfiltrert når kjent (price_history.in_stock, 0017). Dagens rad: live fra offers (0018 BUG 2). Brukes av prishistorikk-sparklinen og som fundament for drop14 (0019).';

grant select on public.v_prislop_price_series to anon, authenticated;

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
  -- en egen serie kun til bruk i drop14.
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

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14 er produktnivå-MIN mot MEDIAN-basislinje i vinduet [-21,-7] dager (0019), beregnet med LEAD()-vindusfunksjon i stedet for korrelert subquery per dag (0020 — 0019-versjonen tok 8s og felte nettsiden via PostgREST sin statement_timeout). Lagerfiltrert når kjent, debut-vakt mot nye butikker/fargevarianter, fallback til først kjente pris for unge produkter. Ingen cap. Fall >50% flagges i post_harvest_check.py. discount er uendret siden 0016.';

grant select on public.v_prislop_products to anon, authenticated;
