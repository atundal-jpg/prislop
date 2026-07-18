-- Kjørt i Supabase 8. juli 2026 (session: proaktiv edisjonsfangst).
-- Støtteview for scraper/check_potential_editions.py (ukentlig vakt).
create or replace view prislop.v_potential_edition_dupes as
with candidates as (
  select
    new.id as new_product_id,
    new.brand,
    new.model as new_model,
    new.gender,
    new.created_at as new_created_at,
    old.id as base_product_id,
    old.model as base_model,
    trim(substring(new.model from length(old.model) + 2)) as residual
  from prislop.products new
  join prislop.products old
    on old.brand = new.brand
    and old.gender = new.gender
    and old.id <> new.id
    and old.created_at < new.created_at
    and lower(new.model) like lower(old.model) || ' %'
  where new.created_at > now() - interval '9 days'
),
tokenized as (
  select *,
    (select array_agg(lower(t)) from unnest(string_to_array(residual, ' ')) as t) as residual_tokens
  from candidates
),
known_modifiers as (
  -- Ekte, vanlige skovarianter — IKKE edisjonshaler. Utvid ved behov (speil av
  -- normalize.py sine _EDITION_*-lister, men motsatt formål: dette er ord som
  -- ALDRI skal flagges, ikke ord som alltid skal strippes).
  select array['gtx','wide','mid','trail','spike','woven','atr','wtr+','st','ff',
               'elite','nitro','pro','plus','low','high']::text[] as toks
)
select new_product_id, brand, new_model, gender, new_created_at, base_product_id, base_model, residual
from tokenized, known_modifiers
where residual <> ''
  and not ( residual_tokens <@ toks or residual ~ '^[0-9]+$' )
order by new_created_at desc;

comment on view prislop.v_potential_edition_dupes is 'Brukes av scraper/check_potential_editions.py (ukentlig vakt). Nye produkter siste ~9 dager hvis modellnavn = et eldre produkts modellnavn + en hale SOM IKKE er en kjent ekte modifikator (known_modifiers) eller et rent versjonstall. Filtrert 8. juli etter test mot levende data: rå prefiks-match ga 38 treff (nesten alle GTX/Wide/Woven/Spike-ekte varianter); med filteret 1 treff.';

-- (Lagre denne filen som scraper/migrations/0002_potential_edition_dupes_view.sql i repoet.)
