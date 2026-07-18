-- Kjørt i Supabase 9. juli 2026 (session: CRO/kundereise → rank_score-gjeld).
--
-- BUG: drop14 (og indirekte rank_score) leste "tidligste price_history-rad
-- innafor siste 14 dager" som basislinje for "prisen for 14 dager siden".
-- Men price_history logger KUN ved prisendring (se 0004-kommentaren og
-- generate_sitemap.py). Det betyr at den raden i praksis viste prisen ETTER
-- siste endring, ikke prisen FØR — så et reelt prisfall for f.eks. 10 dager
-- siden ble usynlig, fordi både "gammel" og "ny" pris i sammenligningen var
-- den samme (nye, lave) verdien. Verifisert før fiks: 577 av de ferske
-- tilbudene hadde base14 = NULL under den gamle logikken (ingen sammenligning
-- mulig i det hele tatt), og 2684 tilbud fikk en annen base14-verdi etter
-- fiksen.
--
-- FIKS: samme prinsipp som v_prislop_price_series sin fremover-fylling —
-- finn siste kjente pris FØR 14-dagersgrensen, begrenset til et 14-dagers
-- fremover-fyllingsvindu (14–28 dager tilbake). Unngår både "ingen rad i
-- vinduet = NULL"-problemet og å sammenligne mot en pris fra måneder tilbake
-- bare fordi ingenting har endret seg siden.
--
-- SIDEMERKNAD: dette er første gang v_prislop_products committes som fil i
-- det hele tatt — viewet har til nå kun eksistert live i Supabase (inkl.
-- subcategory/carbon_plate/waterproof/wide-kolonnene fra 8. juli, som heller
-- aldri ble committet som egen migrasjon). Denne filen er derfor den fulle,
-- gjeldende definisjonen, ikke en diff.

create or replace view public.v_prislop_products as
with fresh_offers as (
  select
    ofr.id,
    ofr.store_id,
    ofr.variant_id,
    ofr.current_price,
    va.product_id,
    va.image_url
  from prislop.offers ofr
  join prislop.variants va on va.id = ofr.variant_id
  where ofr.last_seen_at > now() - interval '2 days'
),
hist as (
  -- peak_price: all-time høyeste registrerte pris for tilbudet (ubegrenset
  -- vindu — OK som den er, MAX() bryr seg ikke om hull i price_history).
  -- base14: se forklaring øverst i filen.
  select
    fo.id as offer_id,
    (
      select max(ph.price)
      from prislop.price_history ph
      where ph.offer_id = fo.id
    ) as peak_price,
    (
      select ph2.price
      from prislop.price_history ph2
      where ph2.offer_id = fo.id
        and ph2.observed_at <= now() - interval '14 days'
        and ph2.observed_at >  now() - interval '28 days'
      order by ph2.observed_at desc
      limit 1
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
agg as (
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
    min(fo.current_price) as from_price,
    count(distinct fo.store_id) as n_stores,
    count(distinct fo.variant_id) as n_colorways,
    coalesce(sum(s.n_in), 0)::bigint as sizes_in_stock,
    (array_agg(fo.image_url) filter (where fo.image_url is not null))[1] as image_url,
    round(coalesce(max(
      case when h.peak_price > fo.current_price
        then least((h.peak_price - fo.current_price) / nullif(h.peak_price, 0), 0.7)
        else null end
    ), 0), 3) as discount,
    round(coalesce(max(
      case when h.base14 > fo.current_price
        then least((h.base14 - fo.current_price) / nullif(h.base14, 0), 0.5)
        else null end
    ), 0), 3) as drop14,
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

comment on view public.v_prislop_products is 'Produktliste for frontend: pris/lager/rank per produkt, siste 2 dagers ferske tilbud. drop14/discount fikset 9. juli til å bruke fremover-fylt prisbasislinje (samme prinsipp som v_prislop_price_series) i stedet for rå price_history, som usynliggjorde reelle prisfall utenfor et 14-dagers endringsvindu.';

grant select on public.v_prislop_products to anon, authenticated;
