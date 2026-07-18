-- 0024_size_chart_ean_derived_ladders.sql
--
-- OPPFØLGING av 0023 (UK-spøkelsesfiksen): den kjente resten var kjøpbare,
-- umappede UK-chips (127 stk) som EAN-broen ikke når fordi ingen annen
-- butikk fører samme EAN med EU-label ennå, og size_chart manglet dekning.
--
-- KILDE — INGEN GJETTING: alle radene under er utledet av vårt eget
-- EAN-belegg («samme strekkode, UK-label i én butikk, EU-label i en
-- annen»), aggregert per merke+kjønn. Kun rene, monotone stiger er tatt
-- med. Ekskludert pga. selvmotsigende enkelt-belegg: Asics dame
-- (5→37.5 OG 6.5→37.5 i samme datasett) og en Mondopoint-avviker
-- (Asics unisex «28»). IKKE dekket her (mangler belegg, tas i probe-sporet
-- — se probe_sportholding_sizefields.py): Hoka (85 av de 127 chipene!),
-- Saucony unisex, Brooks, Nike-yttersizene 12.5/15. Merk at Hoka/Brooks-
-- radene HAR EAN, så EAN-broen selv-leger dem den dagen en annen butikk
-- fører samme fargevariant.
--
-- Stigene legges inn for de fire butikkene som faktisk emitterer UK-labels
-- for disse merkene i dag (loplabbet, sport1, intersport, brukas —
-- Sportholding-plattformen + Brukås). Torshov har egne rader fra før og
-- røres ikke. Stigen er en merke-sannhet (EAN-utledet, butikkuavhengig),
-- butikk-dimensjonen er bare nøkkelgranulariteten viewet slår opp på.
--
-- SIKKERHETSSJEKKER kjørt mot prod 17. juli før anvendelse:
--   (1) 0 kollisjoner: ingen av de 208 mappbare UK-radene har en EU-rad
--       med samme (mappede) størrelse i SAMME tilbud — mappingen fyller
--       hull i EU-stigen, dublerer aldri.
--   (2) size_chart hadde ingen dubletter på (brand, store_slug, gender,
--       uk_label) → unik indeks legges på (viewets LEFT JOIN antar maks
--       én treff-rad; en dublett ville fanne ut størrelsesrader).
-- Bivirkning (ønsket): utsolgte UK-rader for disse kombinasjonene blir nå
-- MAPPET i stedet for filtrert av 0023 — de gjenoppstår som ærlige
-- EU-«utsolgt»-chips.
--
-- v_prislop_products/v_prislop_price_series er uendret (regel 4/5 gjelder
-- ikke); v_prislop_sizes er uendret i DEFINISJON — bare oppslagstabellen
-- den allerede bruker får flere rader.

-- Vern mot fan-out i viewet: maks én chart-rad per nøkkel.
create unique index if not exists size_chart_brand_store_gender_uk_key
  on prislop.size_chart (brand, store_slug, (coalesce(gender, '')), uk_label);

with ladders(brand, gender, uk_label, eu_label) as (
  values
    -- Saucony dame (EAN-belegg 2–3 uavhengige treff per trinn)
    ('Saucony','dame','5.5','36'),  ('Saucony','dame','6','37'),
    ('Saucony','dame','6.5','37.5'),('Saucony','dame','7','38'),
    ('Saucony','dame','7.5','38.5'),('Saucony','dame','8','39'),
    ('Saucony','dame','8.5','40'),  ('Saucony','dame','9','40.5'),
    ('Saucony','dame','9.5','41'),  ('Saucony','dame','10','42'),
    -- Saucony herre (EAN-belegg, konsistent med eksisterende torshov-rader)
    ('Saucony','herre','7','40'),   ('Saucony','herre','7.5','40.5'),
    ('Saucony','herre','8','41'),   ('Saucony','herre','8.5','42'),
    ('Saucony','herre','9','42.5'), ('Saucony','herre','9.5','43'),
    ('Saucony','herre','10','44'),  ('Saucony','herre','10.5','44.5'),
    ('Saucony','herre','11','45'),  ('Saucony','herre','11.5','46'),
    ('Saucony','herre','12','46.5'),('Saucony','herre','12.5','47'),
    -- Asics unisex (EAN-belegg; matcher Asics' herrestige)
    ('Asics','unisex','5','37.5'),  ('Asics','unisex','5.5','38'),
    ('Asics','unisex','6','39'),    ('Asics','unisex','6.5','39.5'),
    ('Asics','unisex','7','40'),    ('Asics','unisex','7.5','40.5'),
    ('Asics','unisex','8','41.5'),  ('Asics','unisex','8.5','42'),
    ('Asics','unisex','9','42.5'),  ('Asics','unisex','9.5','43.5'),
    ('Asics','unisex','10','44'),   ('Asics','unisex','10.5','44.5'),
    ('Asics','unisex','11','45'),   ('Asics','unisex','11.5','46'),
    ('Asics','unisex','12','46.5'),
    -- Mizuno herre (EAN-belegg; klar for den dagen disse butikkene fører Mizuno)
    ('Mizuno','herre','6.5','40'),  ('Mizuno','herre','7','40.5'),
    ('Mizuno','herre','7.5','41'),  ('Mizuno','herre','8','42'),
    ('Mizuno','herre','8.5','42.5'),('Mizuno','herre','9.5','44'),
    ('Mizuno','herre','10','44.5'), ('Mizuno','herre','10.5','45'),
    ('Mizuno','herre','11','46'),   ('Mizuno','herre','11.5','46.5'),
    ('Mizuno','herre','12','47')
),
stores(store_slug) as (
  values ('loplabbet'), ('sport1'), ('intersport'), ('brukas')
)
insert into prislop.size_chart (brand, store_slug, gender, uk_label, eu_label, source)
select l.brand, s.store_slug, l.gender, l.uk_label, l.eu_label,
       'EAN-utledet fra egne data (0024, 17. juli 2026)'
from ladders l
cross join stores s
where not exists (
  select 1 from prislop.size_chart sc
  where sc.brand = l.brand
    and sc.store_slug = s.store_slug
    and coalesce(sc.gender, '') = l.gender
    and sc.uk_label = l.uk_label
);
