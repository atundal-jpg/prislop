-- Kjørt i Supabase 8. juli 2026 (session: prishistorikk-sparkline).
-- Per produkt, per dag: laveste observerte pris på tvers av alle butikker
-- (siste 90 dager). Rå daglig min — bevisst INGEN glatting (ville skjult ekte
-- prisfall). Tidligdata-støy (delvise harvester) forsvinner av seg selv når
-- cron-herdingen gir tette kjøringer og junidagene ruller ut av vinduet.
-- Anon-lesbar som de tre andre v_prislop_*-viewene; ligger i PUBLIC-schemaet
-- (ikke prislop) fordi det er der PostgREST eksponerer frontend-viewene.
create or replace view public.v_prislop_price_series as
select
  v.product_id,
  ph.observed_at::date as day,
  min(ph.price)::numeric as min_price,
  count(distinct o.store_id) as n_stores
from prislop.price_history ph
join prislop.offers o    on o.id = ph.offer_id
join prislop.variants v  on v.id = o.variant_id
where ph.observed_at > now() - interval '90 days'
  and ph.price is not null
group by v.product_id, ph.observed_at::date;

comment on view public.v_prislop_price_series is 'Per produkt, per dag: laveste observerte pris på tvers av alle butikker (siste 90 dager). Brukes av prishistorikk-sparkline i frontend. Anon-lesbar som de tre andre v_prislop_*-viewene.';

grant select on public.v_prislop_price_series to anon, authenticated;

-- (Lagre som scraper/migrations/0004_price_series_view.sql i repoet.)
