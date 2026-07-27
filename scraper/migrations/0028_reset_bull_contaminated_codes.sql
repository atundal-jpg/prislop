-- 0028: nullstill KONTAMINERTE Bull-koder (fallout etter 0027-harvesten).
--
-- IKKE ANVENDT ENNÅ. Denne forutsetter at PARSER-FIKSEN ER MERGET TIL main
-- (Saucony 5+3-formatet + kutt av fri-tekst-søket før «Relaterte produkter»).
-- Kjøres den mens den gamle parseren fortsatt ligger på main, skriver neste
-- harvest de samme feilkodene inn igjen. Migrasjonen håndhever ikke dette
-- selv — den kan ikke se hvilken kode som kjører — så sjekk at fiksen er inne
-- før du kjører den.
--
-- BAKGRUNN
-- Første harvest med den nye parseren (PR #26) ga 648 Bull-tilbud på 648
-- URL-er, men bare 634 distinkte store_sku. Åtte koder satt på flere URL-er,
-- flere på helt ulike produkter. probe_bull_code_source.py viste hvorfor, per
-- side:
--
--   og:image     triumph-23-wide-men-black-white-s21023-200.jpg
--   fra bilde  : None            <- regexen kjente bare Saucony 6+4, ikke 5+3
--   fra etikett: None            <- disse sidene har ingen «Produktnummer»
--   fri tekst  : 2632400-SHAKEOUT  (ETTER «Relaterte produkter»)
--                …/product_image/lc2632400-shakeout-cap-deep-black-photoroom.jpg
--
-- Koden kom altså fra en CAPS i tilbehørs-karusellen. Tilsvarende sto en
-- hatt-kode (1170330-BLK) på fire sko og en quarter-zip-kode (1164155-TLS) på
-- både en Saucony- og en Kiprun-sko.
--
-- Ingen dekning gikk tapt (SKU-broen er nøklet på (sku, product_id), så koder
-- på ulike produkter kan ikke slå sammen rader), men radene står med feil
-- nøkkel. Uten denne nullstillingen ville neste harvest lest RIKTIG kode, ikke
-- funnet den i broen, og laget en ny variant + et nytt tilbud ved siden av —
-- akkurat den rad-multipliseringen 0027 nettopp fjernet. Nullstilt SKU gjør at
-- URL-fallbacken i loaderen adopterer raden og skriver riktig kode inn i den.
--
-- Identifikasjonen trenger ingen hardkodet liste: en colorway-kode tilhører per
-- definisjon ETT produkt, så en store_sku som hos Bull peker på flere
-- product_id er beviselig lest fra feil sted.
--
-- SELECT-FORHÅNDSSVAR (mot prod 27. juli, etter harvesten 12:53):
--
--   select o.store_sku, count(*) as urler, count(distinct v.product_id) as produkter
--   from prislop.offers o
--   join prislop.stores s on s.id = o.store_id
--   join prislop.variants v on v.id = o.variant_id
--   where s.slug = 'bull' and o.store_sku is not null
--   group by o.store_sku having count(distinct v.product_id) > 1;
--
--   -> 8 koder / 22 rader:
--      2632400-SHAKEOUT  5 URL-er / 5 produkter   (Saucony caps)
--      1170330-BLK       4 / 4                    (Saucony trail-hatt)
--      1164330-WHT       3 / 3
--      1164155-TLS       2 / 2                    (quarter-zip; Saucony + Kiprun)
--      1133532-BBLC      2 / 2
--      1155150-BCKT      2 / 2
--      1155151-BCKT      2 / 2
--      220830-AIRY       2 / 2
--   Faktiske tall rapporteres av RAISE NOTICE ved kjøring.
--
-- ETTER KJØRING står disse radene med store_sku = NULL. Det er en TILSIKTET
-- mellomtilstand som varer til neste harvest. Merk at VAKT 2 i 0027 da vil
-- avbryte en ny kjøring av 0027 — som er riktig, den skal kjøres én gang.

begin;

-- Settet plukkes ut FØR noe endres, så steg b ser samme rader som steg a.
create temporary table _bull_kontaminert on commit drop as
with kontaminert as (
    select o.store_sku
      from prislop.offers o
      join prislop.stores s on s.id = o.store_id
      join prislop.variants v on v.id = o.variant_id
     where s.slug = 'bull' and o.store_sku is not null
     group by o.store_sku
    having count(distinct v.product_id) > 1
)
select o.id as offer_id, o.variant_id, o.store_sku
  from prislop.offers o
  join prislop.stores s on s.id = o.store_id
 where s.slug = 'bull'
   and o.store_sku in (select store_sku from kontaminert);

do $$
declare n int; k int;
begin
    select count(*), count(distinct store_sku) into n, k from _bull_kontaminert;
    if n = 0 then
        raise notice 'Ingen kontaminerte koder igjen — ingenting å gjøre.';
    else
        raise notice 'Nullstiller % Bull-rader fordelt på % kontaminerte koder.', n, k;
    end if;
end $$;

-- a) tilbudet mister nøkkelen, så URL-fallbacken adopterer raden neste harvest
update prislop.offers o set store_sku = null
  from _bull_kontaminert k
 where o.id = k.offer_id;

-- b) varianten mister den feilaktige produsentkoden
update prislop.variants v set manufacturer_code = null
 where v.id in (select variant_id from _bull_kontaminert);

commit;

-- ETTERKONTROLL (kjør etter NESTE harvest, ikke med én gang):
--   -- ingen kode skal lenger peke på flere produkter hos Bull
--   select count(*) from (
--     select o.store_sku from prislop.offers o
--     join prislop.stores s on s.id = o.store_id
--     join prislop.variants v on v.id = o.variant_id
--     where s.slug = 'bull' and o.store_sku is not null
--     group by o.store_sku having count(distinct v.product_id) > 1) t;
--   -- forventet: 0
--
--   -- og dekningen skal holde seg: tilbud = distinkte URL-er
--   select count(*), count(distinct url) from prislop.offers o
--   join prislop.stores s on s.id = o.store_id
--   where s.slug = 'bull' and o.last_seen_at > now() - interval '12 hours';
