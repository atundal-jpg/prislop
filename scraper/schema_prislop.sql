-- =====================================================================
--  Prisløp — schema-isolert versjon (bor i `prislop`-schema)
--  Midlertidig samlokalisert i vinmonopolet-prosjektet til VM er over.
--  Alt ligger i schemaet `prislop`, atskilt fra Vinmonopolets tabeller,
--  så hele greia kan dumpes (pg_dump -n prislop) og flyttes til eget
--  prosjekt senere uten å røre noe annet.
-- =====================================================================

create schema if not exists prislop;
create extension if not exists citext;

-- ---------------------------------------------------------------------
--  KATALOG  (offentlig lesbar — ingen persondata)
-- ---------------------------------------------------------------------
create table prislop.stores (
  id       bigint generated always as identity primary key,
  slug     text unique not null,
  name     text not null,
  source   text not null check (source in ('scrape','feed')),
  network  text,
  base_url text,
  active   boolean not null default true
);

create table prislop.products (
  id           uuid primary key default gen_random_uuid(),
  brand        text not null,
  model        text not null,
  gender       text not null check (gender in ('herre','dame','unisex','barn')),
  product_line text,
  category     text not null default 'running',
  created_at   timestamptz not null default now(),
  unique (brand, model, gender)
);

create table prislop.variants (
  id                uuid primary key default gen_random_uuid(),
  product_id        uuid not null references prislop.products(id) on delete cascade,
  color             text,
  manufacturer_code text,                     -- Asics-artikkelkode + farge (bro når EAN mangler)
  image_url         text,
  created_at        timestamptz not null default now()
);
create index on prislop.variants (manufacturer_code);

create table prislop.offers (
  id            uuid primary key default gen_random_uuid(),
  store_id      bigint not null references prislop.stores(id),
  variant_id    uuid   not null references prislop.variants(id) on delete cascade,
  store_sku     text,
  url           text not null,
  currency      text not null default 'NOK',
  current_price numeric(10,2),
  in_stock      boolean,
  last_seen_at  timestamptz not null default now(),
  unique (store_id, variant_id)
);
create index on prislop.offers (variant_id);

create table prislop.offer_sizes (
  id          uuid primary key default gen_random_uuid(),
  offer_id    uuid not null references prislop.offers(id) on delete cascade,
  size_label  text not null,
  ean         text,                           -- EAN-13 (krysskobling) når tilgjengelig
  in_stock    boolean not null default false,
  stock_count integer,
  updated_at  timestamptz not null default now(),
  unique (offer_id, size_label)
);
create index on prislop.offer_sizes (ean);
create index on prislop.offer_sizes (offer_id);

create table prislop.price_history (
  id          bigint generated always as identity primary key,
  offer_id    uuid not null references prislop.offers(id) on delete cascade,
  price       numeric(10,2) not null,
  currency    text not null default 'NOK',
  observed_at timestamptz not null default now()
);
create index on prislop.price_history (offer_id, observed_at desc);

-- ---------------------------------------------------------------------
--  BRUKERE & VARSLER  (persondata — låst, ingen anon-tilgang)
-- ---------------------------------------------------------------------
create table prislop.subscribers (
  id                            uuid primary key default gen_random_uuid(),
  email                         citext unique not null,
  email_verified                boolean not null default false,
  created_at                    timestamptz not null default now(),
  consent_alerts                boolean not null default false,
  consent_alerts_at             timestamptz,
  consent_aggregate_insights    boolean not null default false,
  consent_aggregate_insights_at timestamptz,
  unsubscribed_at               timestamptz
);

create table prislop.alerts (
  id                uuid primary key default gen_random_uuid(),
  subscriber_id     uuid not null references prislop.subscribers(id) on delete cascade,
  product_id        uuid not null references prislop.products(id) on delete cascade,
  size_label        text,
  max_price         numeric(10,2),
  alert_type        text not null default 'both'
                      check (alert_type in ('price_drop','back_in_stock','both')),
  active            boolean not null default true,
  notify_channel    text not null default 'email' check (notify_channel in ('email','ntfy')),
  created_at        timestamptz not null default now(),
  last_triggered_at timestamptz
);
create index on prislop.alerts (product_id) where active;
create index on prislop.alerts (subscriber_id);

create table prislop.alert_events (
  id               bigint generated always as identity primary key,
  alert_id         uuid not null references prislop.alerts(id) on delete cascade,
  offer_id         uuid references prislop.offers(id),
  triggered_at     timestamptz not null default now(),
  price_at_trigger numeric(10,2),
  converted        boolean
);
create index on prislop.alert_events (alert_id);

-- ---------------------------------------------------------------------
--  ETTERSPØRSELS-INNSIKT  (k-anonymisert, samtykke-styrt, kun backend)
-- ---------------------------------------------------------------------
create view prislop.v_demand_insights as
  select
    p.brand, p.model, p.gender, a.size_label,
    (floor(a.max_price / 100) * 100)::int as price_bucket_nok,
    count(distinct a.subscriber_id)       as waiting_buyers
  from prislop.alerts a
  join prislop.subscribers s on s.id = a.subscriber_id
  join prislop.products    p on p.id = a.product_id
  where a.active
    and a.max_price is not null
    and s.consent_aggregate_insights = true
    and s.unsubscribed_at is null
  group by p.brand, p.model, p.gender, a.size_label, price_bucket_nok
  having count(distinct a.subscriber_id) >= 5;

-- ---------------------------------------------------------------------
--  RLS + grants
--  Katalog: lesbar for anon (RLS slipper alle rader). Persondata: ingen
--  grant til anon => utilgjengelig; service_role (backend) omgår RLS.
--  Innsikts-viewet: kun backend, aldri anon.
-- ---------------------------------------------------------------------
alter table prislop.stores        enable row level security;
alter table prislop.products      enable row level security;
alter table prislop.variants      enable row level security;
alter table prislop.offers        enable row level security;
alter table prislop.offer_sizes   enable row level security;
alter table prislop.price_history enable row level security;
alter table prislop.subscribers   enable row level security;
alter table prislop.alerts        enable row level security;
alter table prislop.alert_events  enable row level security;

create policy "katalog les" on prislop.stores        for select using (true);
create policy "katalog les" on prislop.products      for select using (true);
create policy "katalog les" on prislop.variants      for select using (true);
create policy "katalog les" on prislop.offers        for select using (true);
create policy "katalog les" on prislop.offer_sizes   for select using (true);
create policy "katalog les" on prislop.price_history for select using (true);

grant usage on schema prislop to anon, authenticated;
grant select on prislop.stores, prislop.products, prislop.variants,
                prislop.offers, prislop.offer_sizes, prislop.price_history
  to anon, authenticated;

-- persondata + innsikt: ingen anon/authenticated-tilgang
revoke all on prislop.v_demand_insights from anon, authenticated;
