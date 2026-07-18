-- =====================================================================
--  prod_reference.sql — snapshot av DB-objekter som kun har levd i prod
--  (Supabase-prosjekt agmhjcskkjtnwmhzzckx), hentet 18. juli 2026.
--
--  Dette er IKKE en migrasjonsfil og skal ALDRI kjøres blindt mot prod
--  (objektene finnes allerede). Formålet er versjonskontroll/gjenoppbygging:
--  før denne filen fantes, var v_prislop_offers, deler av v_prislop_sizes,
--  create_alert og unsub_alert udokumentert i repoet — et havarert prosjekt
--  kunne ikke gjenskapes fra git alene.
--
--  Endringer i disse objektene skal fortsatt gjøres som nye, nummererte
--  migrasjonsfiler (scraper/migrations/NNNN_*.sql, jf. CLAUDE.md regel 2);
--  oppdater gjerne denne snapshoten i samme PR så den holder seg sann.
--  v_prislop_products og v_prislop_price_series vedlikeholdes allerede i
--  migrasjonene (senest 0022/0020) og er bevisst utelatt her.
-- =====================================================================

-- ---------------------------------------------------------------------
--  public.v_prislop_offers — tilbudslisten frontenden leser.
--  NB: har aldri hatt butikk-eksklusjoner (CLAUDE.md regel 4).
-- ---------------------------------------------------------------------
create or replace view public.v_prislop_offers as
select va.product_id,
       of.id as offer_id,
       st.name as store,
       va.color as colorway,
       of.store_color,
       va.manufacturer_code,
       of.current_price as price,
       of.currency,
       of.url,
       of.in_stock,
       count(*) filter (where os.in_stock) as sizes_in_stock
from prislop.offers of
join prislop.variants va on va.id = of.variant_id
join prislop.stores st on st.id = of.store_id
left join prislop.offer_sizes os on os.offer_id = of.id
where of.last_seen_at > (now() - interval '2 days')
group by va.product_id, of.id, st.name, va.color, of.store_color,
         va.manufacturer_code, of.current_price, of.currency, of.url, of.in_stock;

-- ---------------------------------------------------------------------
--  public.v_prislop_sizes — per-størrelse-listen med UK->EU-mapping.
--  (Sist endret i migrasjon 0023/0024; snapshotet her er prod-fasiten.)
-- ---------------------------------------------------------------------
create or replace view public.v_prislop_sizes as
with eu_map as (
  select offer_sizes.ean,
         mode() within group (order by offer_sizes.size_label) as eu_label
  from prislop.offer_sizes
  where offer_sizes.ean is not null
    and substring(offer_sizes.size_label, '^\d+(?:\.\d+)?')::numeric >= 30
    and substring(offer_sizes.size_label, '^\d+(?:\.\d+)?')::numeric <= 60
  group by offer_sizes.ean
), mapped as (
  select va.product_id,
         os.size_label,
         st.name as store,
         va.color as colorway,
         os.ean,
         os.in_stock,
         os.stock_count,
         ofr.current_price as price,
         ofr.url,
         ofr.id as offer_id,
         btrim(replace(coalesce(
           case
             when substring(os.size_label, '^\d+(?:\.\d+)?')::numeric < 30
               then coalesce(m.eu_label, sc.eu_label)
             else null
           end, os.size_label), ',', '.')) as size
  from prislop.offer_sizes os
  join prislop.offers ofr on ofr.id = os.offer_id
  join prislop.variants va on va.id = ofr.variant_id
  join prislop.stores st on st.id = ofr.store_id
  join prislop.products pr on pr.id = va.product_id
  left join eu_map m on m.ean = os.ean
  left join prislop.size_chart sc
    on sc.brand = pr.brand and sc.store_slug = st.slug
   and (sc.gender is null or sc.gender = pr.gender)
   and sc.uk_label = replace(regexp_replace(os.size_label, '[Hh]$', '.5'), ',', '.')
  where ofr.last_seen_at > (now() - interval '2 days')
)
select product_id, size_label, store, colorway, ean, in_stock, stock_count,
       price, url, offer_id, size
from mapped
where in_stock
   or coalesce(substring(size, '^\d+(?:\.\d+)?')::numeric >= 30, true);

-- ---------------------------------------------------------------------
--  public.create_alert — RPC frontenden kaller etter magic-link-innlogging
--  (index.html: activatePendingAlert). SECURITY DEFINER; e-post fra JWT.
-- ---------------------------------------------------------------------
create or replace function public.create_alert(p_product_id uuid, p_size_label text default null, p_max_price numeric default null)
returns uuid
language plpgsql
security definer
set search_path to 'prislop', 'public'
as $function$
declare
  v_email text := lower(coalesce(auth.jwt() ->> 'email', ''));
  v_sub   uuid;
  v_alert uuid;
begin
  if v_email = '' then
    raise exception 'ingen verifisert e-post i token';
  end if;
  if p_max_price is not null and (p_max_price <= 0 or p_max_price > 100000) then
    raise exception 'ugyldig prisgrense';
  end if;

  insert into prislop.subscribers (email, email_verified, consent_alerts, consent_alerts_at)
  values (v_email, true, true, now())
  on conflict (email) do update
     set email_verified = true,
         consent_alerts = true,
         consent_alerts_at = coalesce(subscribers.consent_alerts_at, now()),
         unsubscribed_at = null
  returning id into v_sub;

  insert into prislop.alerts (subscriber_id, product_id, size_label, max_price,
                              alert_type, active)
  values (v_sub, p_product_id, nullif(btrim(p_size_label), ''), p_max_price,
          case when p_max_price is null then 'back_in_stock' else 'price_drop' end,
          true)
  on conflict (subscriber_id, product_id, coalesce(size_label, '*'))
  do update set max_price = excluded.max_price,
                alert_type = excluded.alert_type,
                active = true
  returning id into v_alert;

  return v_alert;
end $function$;

-- ---------------------------------------------------------------------
--  public.unsub_alert — RPC bak alerts-unsub-edge-funksjonen.
-- ---------------------------------------------------------------------
create or replace function public.unsub_alert(p_alert_id uuid, p_all boolean default false)
returns text
language plpgsql
security definer
set search_path to 'prislop', 'public'
as $function$
declare
  v_sub uuid;
begin
  select subscriber_id into v_sub from prislop.alerts where id = p_alert_id;
  if v_sub is null then
    return 'not_found';
  end if;
  if p_all then
    update prislop.alerts set active = false where subscriber_id = v_sub;
    update prislop.subscribers set unsubscribed_at = now() where id = v_sub;
    return 'all_stopped';
  end if;
  update prislop.alerts set active = false where id = p_alert_id;
  return 'stopped';
end $function$;
