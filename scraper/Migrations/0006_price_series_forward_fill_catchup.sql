-- Dokumentasjons-catchup (9. juli 2026) — INGEN funksjonell endring.
--
-- v_prislop_price_series ble oppgradert til fremover-fylling i en tidligere
-- økt (samme prinsipp som nå brukes til å fikse drop14 i 0005), men den
-- oppdaterte versjonen ble aldri committet som fil — 0004_price_series_view.sql
-- i repoet viser fortsatt den ENKLE, FØR-fiks versjonen (rå daglig min, ingen
-- fremover-fylling). Denne filen henter viewet i sync med det som faktisk
-- kjører i prod, slik at migrasjonshistorikken er til å stole på.
--
-- Fremover-fylling: for hvert produkt × butikk × dag, bruk siste kjente pris
-- innafor et 14-dagers vindu bakover (i stedet for å kreve en prisendring
-- akkurat den dagen — price_history logger kun ved endring). Gir en
-- sammenhengende sparkline uten å late som prisen er ukjent bare fordi den
-- ikke har beveget seg.

create or replace view public.v_prislop_price_series as
with obs as (
  select
    v.product_id,
    o.store_id,
    ph.observed_at::date as day,
    (array_agg(ph.price order by ph.observed_at desc))[1] as price
  from prislop.price_history ph
  join prislop.offers o    on o.id = ph.offer_id
  join prislop.variants v  on v.id = o.variant_id
  where ph.observed_at > now() - interval '104 days'
    and ph.price is not null
  group by v.product_id, o.store_id, ph.observed_at::date
),
bounds as (
  select product_id, min(day) as first_day
  from obs
  group by product_id
),
days as (
  select b.product_id, gs::date as day
  from bounds b
  cross join lateral generate_series(b.first_day::timestamptz, current_date::timestamptz, interval '1 day') gs
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
    (
      select o2.price
      from obs o2
      where o2.product_id = p.product_id
        and o2.store_id = p.store_id
        and o2.day <= p.day
        and o2.day >  p.day - interval '14 days'
      order by o2.day desc
      limit 1
    ) as ff_price
  from pairs p
)
select
  product_id,
  day,
  min(ff_price) as min_price,
  count(ff_price) as n_stores
from filled
where ff_price is not null
  and day > current_date - interval '90 days'
group by product_id, day;

comment on view public.v_prislop_price_series is 'Per produkt, per dag: laveste fremover-fylte pris på tvers av butikker (siste 90 dager, 14-dagers fremover-fyllingsvindu). Brukes av prishistorikk-sparkline i frontend og som forbilde for drop14-fiksen i v_prislop_products (0005). Anon-lesbar som de andre v_prislop_*-viewene.';

grant select on public.v_prislop_price_series to anon, authenticated;
