-- 0013_reverse_xxl_quarantine.sql
--
-- Reverserer 0012 (temp_exclude_xxl_stale_prices, 20260710102403).
-- XXL-prisbugen er rettet i xxl_parser.py (isSelected-fiks, 11. juli):
-- parseren emitter naa kun den viste fargevariantens egen pris, ikke
-- sosken-fargenes lante/kopierte pris. Full harvest 11. juli bekreftet:
--   * 337 XXL-tilbud (= discovery-settet, ingen tap)
--   * 68 distinkte priser, spenn 289-2599 (ikke lenger flatt)
--   * Vomero 18-firklover: 1519/1399/1749/1229 (fire ulike, korrekte)
--
-- Endringen i begge views er identisk: fjern den midlertidige
--   AND <store_id> <> (SELECT id FROM prislop.stores WHERE name = 'XXL')
-- filter-klausulen som 0012 la inn. Alt annet er uendret.
--
-- MERK (v_prislop_price_series): denne leser price_history 104 dager
-- tilbake. Historiske XXL-punkter fra 9.-11. juli inneholder fortsatt de
-- feilaktige 1229-verdiene fra last-write-wins-perioden, saa XXL-kurvene
-- kan vise et kunstig prisfall de neste par ukene til friske punkter
-- dominerer. Vurder egen opprydding av de gamle punktene ved behov.

begin;

-- 1) v_prislop_products: slipp XXL inn i produkt-/rank-viewet igjen.
create or replace view public.v_prislop_products as
 WITH fresh_offers AS (
         SELECT ofr.id,
            ofr.store_id,
            ofr.variant_id,
            ofr.current_price,
            va.product_id,
            va.image_url
           FROM prislop.offers ofr
             JOIN prislop.variants va ON va.id = ofr.variant_id
          WHERE ofr.last_seen_at > (now() - '2 days'::interval)
        ), hist AS (
         SELECT fo.id AS offer_id,
            ( SELECT max(ph.price) AS max
                   FROM prislop.price_history ph
                  WHERE ph.offer_id = fo.id) AS peak_price,
            ( SELECT ph2.price
                   FROM prislop.price_history ph2
                  WHERE ph2.offer_id = fo.id AND ph2.observed_at <= (now() - '14 days'::interval) AND ph2.observed_at > (now() - '28 days'::interval)
                  ORDER BY ph2.observed_at DESC
                 LIMIT 1) AS base14
           FROM fresh_offers fo
        ), sz AS (
         SELECT os.offer_id,
            count(*) AS n_all,
            count(*) FILTER (WHERE os.in_stock) AS n_in
           FROM prislop.offer_sizes os
             JOIN fresh_offers fo ON fo.id = os.offer_id
          GROUP BY os.offer_id
        ), agg AS (
         SELECT pr.id AS product_id,
            pr.brand,
            pr.model,
            pr.gender,
            pr.product_line,
            pr.category,
            pr.subcategory,
            pr.carbon_plate,
            pr.waterproof,
            pr.wide,
            min(fo.current_price) AS from_price,
            count(DISTINCT fo.store_id) AS n_stores,
            count(DISTINCT fo.variant_id) AS n_colorways,
            COALESCE(sum(s.n_in), 0::numeric)::bigint AS sizes_in_stock,
            (array_agg(fo.image_url) FILTER (WHERE fo.image_url IS NOT NULL))[1] AS image_url,
            round(COALESCE(max(
                CASE
                    WHEN h.peak_price > fo.current_price THEN LEAST((h.peak_price - fo.current_price) / NULLIF(h.peak_price, 0::numeric), 0.7)
                    ELSE NULL::numeric
                END), 0::numeric), 3) AS discount,
            round(COALESCE(max(
                CASE
                    WHEN h.base14 > fo.current_price THEN LEAST((h.base14 - fo.current_price) / NULLIF(h.base14, 0::numeric), 0.5)
                    ELSE NULL::numeric
                END), 0::numeric), 3) AS drop14,
            round(
                CASE
                    WHEN COALESCE(sum(s.n_all), 0::numeric) = 0::numeric THEN 0::numeric
                    ELSE sum(s.n_in) / sum(s.n_all)
                END, 3) AS stock_ratio
           FROM prislop.products pr
             JOIN fresh_offers fo ON fo.product_id = pr.id
             LEFT JOIN sz s ON s.offer_id = fo.id
             LEFT JOIN hist h ON h.offer_id = fo.id
          GROUP BY pr.id, pr.brand, pr.model, pr.gender, pr.product_line, pr.category, pr.subcategory, pr.carbon_plate, pr.waterproof, pr.wide
        )
 SELECT product_id,
    brand,
    model,
    gender,
    product_line,
    category,
    from_price,
    n_stores,
    n_colorways,
    sizes_in_stock,
    image_url,
    discount,
    drop14,
    stock_ratio,
    round((2::double precision * ln((1 + n_stores)::double precision) + 1::double precision * ln((1 + n_colorways)::double precision) + (1.5 * stock_ratio)::double precision + (2::numeric * discount)::double precision + (3::numeric * drop14)::double precision +
        CASE
            WHEN sizes_in_stock < 5 THEN '-2'::integer
            ELSE 0
        END::double precision)::numeric, 3) AS rank_score,
    subcategory,
    carbon_plate,
    waterproof,
    wide
   FROM agg;

-- 2) v_prislop_price_series: slipp XXL inn i pris-historikk-serien igjen.
create or replace view public.v_prislop_price_series as
 WITH obs AS (
         SELECT v.product_id,
            o.store_id,
            ph.observed_at::date AS day,
            (array_agg(ph.price ORDER BY ph.observed_at DESC))[1] AS price
           FROM prislop.price_history ph
             JOIN prislop.offers o ON o.id = ph.offer_id
             JOIN prislop.variants v ON v.id = o.variant_id
          WHERE ph.observed_at > (now() - '104 days'::interval) AND ph.price IS NOT NULL
          GROUP BY v.product_id, o.store_id, (ph.observed_at::date)
        ), bounds AS (
         SELECT obs.product_id,
            min(obs.day) AS first_day
           FROM obs
          GROUP BY obs.product_id
        ), days AS (
         SELECT b.product_id,
            gs.gs::date AS day
           FROM bounds b
             CROSS JOIN LATERAL generate_series(b.first_day::timestamp with time zone, CURRENT_DATE::timestamp with time zone, '1 day'::interval) gs(gs)
        ), pairs AS (
         SELECT DISTINCT d.product_id,
            d.day,
            o.store_id
           FROM days d
             JOIN obs o ON o.product_id = d.product_id
        ), filled AS (
         SELECT p.product_id,
            p.day,
            p.store_id,
            ( SELECT o2.price
                   FROM obs o2
                  WHERE o2.product_id = p.product_id AND o2.store_id = p.store_id AND o2.day <= p.day AND o2.day > (p.day - '14 days'::interval)
                  ORDER BY o2.day DESC
                 LIMIT 1) AS ff_price
           FROM pairs p
        )
 SELECT product_id,
    day,
    min(ff_price) AS min_price,
    count(ff_price) AS n_stores
   FROM filled
  WHERE ff_price IS NOT NULL AND day > (CURRENT_DATE - '90 days'::interval)
  GROUP BY product_id, day;

commit;
