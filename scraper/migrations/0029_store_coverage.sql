-- 0029_store_coverage.sql
--
-- Dekningshistorikk per butikk per kjøring.
--
-- Bakgrunn (28. juli): Bull mistet stille URL-er over uker — 648 av 667
-- distinkte URL-er i siste last, spredt over flere kjøringer siden 20. juni.
-- Ingen eksisterende vakt fanget det: rad-multipliseringsvakten ser på
-- (url, store_sku)-duplikater, den stille-butikk-vakten krever NULL ferske
-- tilbud, og re-split-vakten ser bare totalt produkttall på tvers av alle
-- butikker (et fall på 19 URL-er hos én butikk drukner i ~870 produkter).
--
-- prislop.offers kan ikke rekonstruere historikken selv: hver rad har bare
-- SISTE last_seen_at, så en URL som ble sett i hver kjøring finnes kun i
-- nyeste bøtte. «Distinkte URL-er i kjøring N» må derfor skrives ned mens
-- kjøringen pågår. Denne tabellen gjør akkurat det, og
-- post_harvest_check.warn_coverage_drop sammenligner kjøringens tall mot
-- butikkens rullerende maks siste 7 døgn.
--
-- Ingen view-endringer: v_prislop_products og v_prislop_price_series er
-- urørt (regel 5), og tabellen leses kun av post_harvest_check.

create table if not exists prislop.store_coverage (
    id          bigserial primary key,
    store_id    integer not null references prislop.stores (id) on delete cascade,
    run_at      timestamptz not null default now(),
    url_count   integer not null,
    offer_count integer not null
);

-- Vakten slår opp «maks siste 7 døgn per butikk» hver kjøring.
create index if not exists store_coverage_store_run_idx
    on prislop.store_coverage (store_id, run_at desc);

comment on table prislop.store_coverage is
    'Distinkte produkt-URL-er og tilbud per butikk per harvest. Skrives av '
    'post_harvest_check.py; brukes til dekningsvakten (rullerende maks 7 døgn). '
    'Ren observabilitet — ingen frontend-view leser den.';
