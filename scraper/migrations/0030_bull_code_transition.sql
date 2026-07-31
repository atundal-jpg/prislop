-- 0030_bull_code_transition.sql
--
-- Overgangsopprydding for fargevelger-fiksen i bull_parser (PR #28).
--
-- BAKGRUNN
-- Parseren sluttet å hente artikkelkode fra den uforankrede fri-tekst-grenen,
-- fordi dokumenthodet inneholder fargevelgeren og «første treff» der er
-- søskenfargens kode. Målt A/B mot ekte markup 31. juli: gammel kjede gir 110
-- nøkler / 12 kollisjoner / 23 tapte URL-er, ny kjede 133 / 0 / 0. Prod hadde
-- nøyaktig 110 distinkte Saucony-URL-er i siste last — modellen traff eksakt.
--
-- HVORFOR DENNE MIGRASJONEN TRENGS
-- De feilaktige kodene ble skrevet TILBAKE i databasen etter 0028: 13 Bull-
-- rader står i dag med offers.store_sku = variants.manufacturer_code = en
-- kollidert kode. Etter fiksen kommer recorden med store_sku = JSON-LD-GTIN,
-- som ikke matcher den lagrede koden. Da bommer både kode-steget og
-- SKU-steget i get_or_create_variant, og URL-fallbacken krever
-- `not sku or hit[1] is None` — begge usanne, siden recorden HAR sku (GTIN)
-- og den lagrede raden HAR store_sku (koden). Loaderen ville derfor laget ny
-- variant + nytt tilbud, latt den gamle raden bli utsolgt-flagget, og
-- prishistorikken ville blitt stående igjen på den forlatte raden.
--
-- Ved å nulle store_sku blir `hit[1] is None` sann, URL-fallbacken adopterer
-- den EKSISTERENDE raden, og upsert_offer skriver den ferske GTIN-en inn i
-- samme kjøring. Ingen nye rader, ingen brutt prishistorikk.
--
-- AVGRENSNING
-- 1) store_sku nulles kun for Bull-tilbud på Saucony-produkter der store_sku
--    er kode-formet (ikke GTIN). Andre merker hos Bull henter koden fra
--    forankrede kilder (og:image / «Produktnummer» / «Art#») og får samme
--    verdi som før — de trenger ingen overgang. Nullingen er uansett rent
--    transitorisk: upsert_offer skriver store_sku på nytt hver kjøring.
-- 2) manufacturer_code nulles kun på varianter som BARE Bull har tilbud på,
--    og bare for de bevist kolliderte kodene. S11023-121 er bevisst utelatt:
--    den varianten deles med Olympia, og en nulling der ville revet ned en
--    ekte kryss-butikk-sammenslåing. Riktig kode læres uansett tilbake neste
--    kjøring — get_or_create_variant arver koden når varianten mangler den.
--
-- Ingen view-endringer (regel 5). Kjør FØR første harvest etter at PR #28 er
-- merget, ellers skriver den gamle parseren kodene inn igjen.

begin;

-- 1) Nullstill store_sku slik at URL-fallbacken adopterer radene på plass.
update prislop.offers o
   set store_sku = null
  from prislop.stores s,
       prislop.variants v,
       prislop.products p
 where s.id = o.store_id
   and s.slug = 'bull'
   and v.id = o.variant_id
   and p.id = v.product_id
   and p.brand = 'Saucony'
   and o.store_sku is not null
   and o.store_sku !~ '^[0-9]{8,14}$';       -- behold ekte GTIN-er

-- 2) Fjern de bevist kolliderte kodene fra varianter bare Bull har.
update prislop.variants v
   set manufacturer_code = null
 where v.manufacturer_code in (
         'S30994-285','S11007-144','S21007-402','S10996-130','S20996-100',
         'S11026-226','S21026-201','S11020-130','S21020-172','S10990-150',
         'S20990-161')                       -- S11023-121 utelatt: delt med Olympia
   and not exists (
         select 1
           from prislop.offers o
           join prislop.stores s on s.id = o.store_id
          where o.variant_id = v.id
            and s.slug <> 'bull');

commit;
