-- Kjørt i Supabase 10. juli 2026 (P0.2: klikk-redirect-laget).
--
-- Utgående klikk-måling + fremtidig affiliate-innbyttepunkt. Arkitektur:
-- GitHub Pages er statisk → redirecten ligger som Supabase Edge Function
-- («ut», deployet med verify_jwt=false — lenker må virke uten auth-header,
-- også fra e-post; lekker ingenting sensitivt, ugyldig offer → forsiden).
-- Frontenden ruter alle «Til butikk»-lenker via
--   https://<proj>.supabase.co/functions/v1/ut?offer=<offer_uuid>&src=web
-- JSON-LD-schemaen beholder BEVISST direkte butikk-URL-er (redirect i
-- schema er dårlig SEO-praksis + bot-klikk ville forurenset statistikken).
--
-- prislop-skjemaet er ikke PostgREST-eksponert (derav v_prislop_*-viewene),
-- så funksjonen kaller én SECURITY DEFINER-RPC som gjør logging + oppslag
-- i samme rundtur. Kun service_role har execute.
--
-- Affiliate-innbytte senere: AFFILIATE_WRAP-mappen i Edge Function-koden
-- (supabase/functions/ut/index.ts) — én endring der per butikk-avtale,
-- null endring i frontend.

create table if not exists prislop.clicks (
  id bigint generated always as identity primary key,
  clicked_at timestamptz not null default now(),
  offer_id uuid references prislop.offers(id) on delete set null,
  store_id bigint,
  src text,
  ua text,
  referer text
);
create index if not exists clicks_clicked_at_idx on prislop.clicks (clicked_at);
create index if not exists clicks_store_id_idx on prislop.clicks (store_id, clicked_at);
alter table prislop.clicks enable row level security;
-- Ingen policies: kun service_role (Edge Function) kan skrive/lese.
comment on table prislop.clicks is 'Utgående klikk via /ut-redirecten (Edge Function). Grunnlag for affiliate-dokumentasjon: klikk per butikk per periode. store_id uten FK med vilje — tilbud slettes/byttes ved harvest, men klikkstatistikken skal bestå.';

create or replace function public.ut_click(p_offer uuid, p_src text, p_ua text, p_ref text)
returns table(url text, store_id bigint)
language plpgsql
security definer
set search_path = prislop, public
as $$
begin
  return query
  with o as (
    select ofr.id, ofr.url, ofr.store_id from prislop.offers ofr where ofr.id = p_offer
  ), ins as (
    insert into prislop.clicks (offer_id, store_id, src, ua, referer)
    select o.id, o.store_id, left(p_src,16), left(p_ua,200), left(p_ref,200) from o
  )
  select o.url, o.store_id from o;
end $$;

revoke execute on function public.ut_click(uuid, text, text, text) from public, anon, authenticated;
grant execute on function public.ut_click(uuid, text, text, text) to service_role;
comment on function public.ut_click is 'Klikk-redirect-lagets ene rundtur: logger klikket i prislop.clicks og returnerer butikk-URL + store_id for /ut Edge Function. SECURITY DEFINER fordi prislop-skjemaet ikke er PostgREST-eksponert.';
