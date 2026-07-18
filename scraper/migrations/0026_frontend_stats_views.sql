-- 0026: to små hjelpe-views for frontendens sidelast.
--
-- Bakgrunn: index.html hentet ved HVER sidelast (1) alle lager-rader fra
-- v_prislop_sizes (titusener av rader) bare for å bygge størrelses-
-- dropdownen, og (2) alle tilbudsrader fra v_prislop_offers bare for å
-- telle distinkte butikker i hero-pillene. Disse viewene gjør aggregeringen
-- server-side, så klienten får hhv. ~40 og 1 rad i stedet.
--
-- NB: dette er NYE views — v_prislop_products/v_prislop_price_series
-- (regel 4/5 i CLAUDE.md) røres ikke. Frontenden (samme PR) prøver disse
-- endepunktene først og faller tilbake til de gamle, tunge spørringene om
-- de ikke finnes — trygt å merge koden før migrasjonen er kjørt.
--
-- Før prod (samme disiplin som regel 5, selv om viewene er nye):
--   explain analyze select * from public.v_prislop_size_options;
--   explain analyze select * from public.v_prislop_stats;
-- skal begge ligge langt under anon-rollens 3s statement_timeout.

create or replace view public.v_prislop_size_options as
select distinct size
from public.v_prislop_sizes
where in_stock;

create or replace view public.v_prislop_stats as
select count(distinct store)::int as n_stores
from public.v_prislop_offers;

grant select on public.v_prislop_size_options, public.v_prislop_stats
  to anon, authenticated;
