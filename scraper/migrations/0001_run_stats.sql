-- Kjørt i Supabase 7. juli 2026 (session: CI-vakter).
-- Støttetabell for scraper/post_harvest_check.py (re-split-vakten).
create table if not exists prislop.run_stats (
  id bigint generated always as identity primary key,
  run_at timestamptz not null default now(),
  products_count integer not null,
  offers_count integer not null,
  note text
);
comment on table prislop.run_stats is 'Én rad per harvest; brukes av post_harvest_check.py til å oppdage re-split av produkter.';

-- (Lagre denne filen som scraper/migrations/0001_run_stats.sql i repoet.)
