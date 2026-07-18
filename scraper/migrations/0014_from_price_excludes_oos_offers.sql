-- 0014_from_price_excludes_oos_offers.sql
--
-- Bug: kortets "Lavest nå"-tall (v_prislop_products.from_price) var
-- min(current_price) over ALLE ferske tilbud, uansett lagerstatus. Dermed
-- kunne toppfeltet vise prisen til en butikk som er utsolgt for varen
-- (sett på Zoom Fly 6 og Novablast 5 14. juli — butikken med lavest pris
-- var tagget «Utsolgt» i butikklista, men prisen sto likevel i "Lavest nå").
--
-- Butikklista (storesHTML i index.html) har alltid gjort dette riktig:
-- "Lavest"-badgen der går kun til billigste tilbud der o.in_stock !== false
-- (null/ukjent lagerstatus telles som tilgjengelig, kun eksplisitt false
-- ekskluderes). Denne migrasjonen gjør at from_price bruker samme regel,
-- så topptallet og butikklistas "Lavest"-badge alltid peker på samme tilbud.
--
-- Endring: fresh_offers eksponerer nå ofr.in_stock, og from_price
-- filtreres på COALESCE(fo.in_stock, true) — identisk semantikk med
-- frontendens `o.in_stock !== false`.
--
-- Ingen endring i v_prislop_price_series: sparklinjen er allerede
-- eksplisitt merket "Laveste pris på tvers av farger og størrelser — velg
-- størrelse under for å se hva som faktisk er på lager" (index.html:1293-94),
-- så historikk-grafen skal fortsatt vise laveste pris uansett lagerstatus.

begin;

create or replace view public.v_prislop_products as
 WITH fresh_offers AS (
         SELECT ofr.id,
            ofr.store_id,
            ofr.variant_id,
            ofr.current_price,
            ofr.in_stock,
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
            min(fo.current_price) FILTER (WHERE COALESCE(fo.in_stock, true)) AS from_price,
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

commit;
