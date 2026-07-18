-- 0021_deal_gap_columns.sql
--
-- «Godt kjøp»-signalet: to nye kolonner i v_prislop_products som flagger
-- produkter der én (eller to) butikker ligger vesentlig under prisnivået
-- hos de øvrige — det som fremstår som et tilbud, uavhengig av om prisen
-- nylig har falt (drop14 er tidsdimensjonen; dette er tverrsnittet).
-- Typeeksempel: MetaSpeed Sky Tokyo — 1 800 hos Foss Sport mot 2 250/3 000/
-- 3 000 hos de andre, uten noe nylig prisfall hos Foss.
--
--   deal_gap    numeric  1 − (beste pris / median av de ANDRE butikkenes
--                        laveste pris). NULL når kravene under ikke er
--                        oppfylt — frontend trenger bare null-sjekke.
--   deal_store  text     Visningsnavnet (stores.name) på butikken med
--                        beste pris. NULL sammen med deal_gap.
--
-- KRAV for flagg (kalibrert mot ekte data 17. juli, se PR-beskrivelsen):
--
-- (1) MINST 3 BUTIKKER med fersk on-lager-pris (n_others >= 2). Med færre
--     finnes ingen «de øvrige» å sammenligne mot.
--
-- (2) BESTE PRIS <= 75 % AV MEDIANEN av de andre butikkenes laveste pris.
--     MEDIAN av de andre — ikke avstand til nest billigste — fordi
--     nest-billigste-varianten bommer når TO butikker er billige (MetaSpeed-
--     eksempelet: gap til nest billigste er bare 10 %, mot medianen 31 %).
--     Median er også robust mot én enkelt feilpriset dyr butikk.
--     Kalibrering 17. juli: 25 % => 79 flagg fordelt på alle 9 butikker
--     (maks 21 % på én butikk), toppen åpenbart ekte tilbud. 30 % => 59.
--
-- (3) MINST 3 STØRRELSER PÅ LAGER i det konkrete billigste tilbudet.
--     Uten dette hadde 29 av 79 flagg (37 %) pekt på et tilbud med bare
--     1–2 størrelser igjen — en «Godt kjøp»-badge som skuffer ved klikk.
--     Kravet gjelder tilbudet som SETTER prisen (samme som from_price),
--     ikke butikkens totale lager.
--
-- Bevisste valg:
-- - Sammenligningen er PRODUKTNIVÅ (billigste pris per butikk på tvers av
--   farger) — samme nivå som from_price og hele kort-UI-et, så påstanden
--   er direkte etterprøvbar i butikklista brukeren ser. Flagget utløses av
--   ETT konkret tilbud (én fargevariant); badge-tekst skal peke på funnet
--   («X kr hos Butikk»), aldri påstå at butikken generelt er billigst.
--   En skjerpet per-fargevariant-sammenligning (samme farge hos flere
--   butikker — mulig for ~60 % av flaggene) er vurdert og utsatt til egen
--   migrasjon; den trenger en UI-flate som ikke finnes ennå.
-- - Terskler ligger som literaler her (views har ikke parametre): 0.75,
--   n_others >= 2, n_in >= 3. Endres de, endres også metodeteksten i
--   index.html (DEAL_CONTENT/AEO) — de to skal alltid fortelle det samme.
-- - rank_score er UENDRET — signalet skal synliggjøres eksplisitt (badge/
--   landingsside), ikke stokke om «Anbefalt» stille.
-- - v_prislop_price_series er UENDRET (regel 4 i CLAUDE.md gjelder
--   butikk-filtre; ingen slike endres her).
-- - Beregningen bruker KUN fresh_offers + offer_sizes (ingen price_history)
--   — marginal kostnad, ikke i slekt med 0018/0020-ytelsesfellene. Regel 5
--   (EXPLAIN ANALYZE + dublett-sjekk) kjøres like fullt før prod.
-- - Vakt: post_harvest_check.py får en ADVARSEL (bevisst ikke rød kjøring
--   — et lovlig sesongsalg kan konsentrere flaggene hos én butikk) når én
--   butikk står for en for stor andel av flaggene.
--
-- drop14, discount, from_price og rank_score er UENDRET av denne
-- migrasjonen; hele viewet gjenskapes kun fordi CREATE OR REPLACE VIEW
-- krever full definisjon. Grunnteksten er identisk med 0020.

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
  d.deal_gap, d.deal_store
from agg
left join deal d on d.product_id = agg.product_id;

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14 er produktnivå-MIN mot MEDIAN-basislinje i vinduet [-21,-7] dager (0019), beregnet med LEAD()-vindusfunksjon i stedet for korrelert subquery per dag (0020 — 0019-versjonen tok 8s og felte nettsiden via PostgREST sin statement_timeout). Lagerfiltrert når kjent, debut-vakt mot nye butikker/fargevarianter, fallback til først kjente pris for unge produkter. Ingen cap. Fall >50% flagges i post_harvest_check.py. discount er uendret siden 0016. deal_gap/deal_store (0021): «godt kjøp»-flagg når billigste butikk ligger >=25% under medianen av de andre butikkenes laveste pris, minst 3 butikker og minst 3 størrelser på lager i det billigste tilbudet; NULL ellers. Skjev butikk-konsentrasjon i flaggene ADVARES (ikke feiles) i post_harvest_check.py.';

grant select on public.v_prislop_products to anon, authenticated;
