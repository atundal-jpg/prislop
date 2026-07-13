# CLAUDE.md — Prisløp

## Hva dette er
Prisløp (prisløp.no, punycode `xn--prislp-fya.no`) er en prissammenligningstjeneste
for løpesko fra 8 norske nettbutikker: laveste pris per modell, lagerstatus per
størrelse, prishistorikk og e-postvarsler ved prisfall. All tekst mot brukere er
på norsk (nb).

## Arkitektur
- **Frontend:** én statisk `index.html` på GitHub Pages (deploy fra `main`, root,
  custom domain `xn--prislp-fya.no`). Ingen build-steg, vanilla JS. All ruting er
  klient-side (`?product=`, `?kategori=`, `?prisfall`) via `history.replaceState`.
- **Data:** Supabase-prosjekt `agmhjcskkjtnwmhzzckx`. Kildedata i skjema
  `prislop.*` (products, variants, offers, offer_sizes, price_history, stores,
  run_stats, clicks). Frontend leser KUN public-views: `v_prislop_products`,
  `v_prislop_offers`, `v_prislop_sizes`, `v_prislop_price_series`.
- **Scraper:** Python i `scraper/`, kjøres av `.github/workflows/scrape.yml`
  hver 6. time (discovery → parsere per butikk → loader → post_harvest_check →
  classify_categories → generate_sitemap). Normal kjøretid ~17–27 min;
  45+ min betyr at noe er galt. Pinger healthchecks.io.
- **Klikk-redirect:** Edge Function `supabase/functions/ut/index.ts`
  (`/ut?offer=<uuid>&src=web|email`) logger til `prislop.clicks` og 302-er til
  butikken. `verify_jwt` er av (kreves for e-postlenker). `AFFILIATE_WRAP` i
  samme fil er innbyttepunktet når affiliateavtaler lander.

## Ufravikelige regler
1. **Punycode-domenet er ALLTID `xn--prislp-fya.no` — aldri `-vxa`.** Gjelder
   canonical, OG-tagger, sitemap, robots.txt og JSON-LD.
2. **DB-endringer skrives alltid som ny, nummerert migrasjonsfil**
   `scraper/migrations/NNNN_kort_beskrivelse.sql` (neste ledige nummer).
   Endre aldri en allerede anvendt migrasjonsfil. Migrasjoner anvendes mot
   databasen i et separat steg (Supabase MCP eller manuelt) — anta aldri at
   «committet» betyr «kjørt», og si eksplisitt fra når en fil gjenstår å kjøre.
3. **Probe-scripts** (`scraper/probe_*.py`) kjøres via `probe.yml`
   (workflow_dispatch) og skal KUN bruke Python-stdlib — `requests` er ikke
   installert i det miljøet.
4. **Views endres i par:** `v_prislop_products` og `v_prislop_price_series` må
   oppdateres sammen når butikk-filtre legges til eller fjernes (jf.
   0012/0013-karantenehistorikken). `v_prislop_offers` har aldri hatt
   butikk-eksklusjoner.
5. **Frontend-mønsteret bevares:** én fil, ingen rammeverk. Nye landingssider
   følger `?kategori`-mønsteret — `history.replaceState`, egen
   title/canonical/OG/meta, CollectionPage/ItemList-JSON-LD, og en synlig
   AEO-linje på siden som er identisk med teksten i FAQPage-schemaet.
6. **Utgående butikklenker i UI går alltid via `/ut`-redirecten** (`outUrl`) —
   aldri direkte butikk-URL. JSON-LD beholder derimot bevisst direkte
   butikk-URL-er (SEO + ren statistikk).

## Kjente feilsignaturer — ikke gjenta disse
- **Bull-bugen (juli 2026):** parserens PRICE_RE tok første «tall,-» i HTML-en,
  som var et sidefast fraktbanner → alle 160 tilbud fikk samme pris i ukevis.
  Lærdom: les pris fra JSON-LD eller annen strukturert kilde med forankring,
  aldri første regex-treff i rå HTML. Banner alene skal gi `None`, ikke en pris.
- **XXL-bugen (juli 2026):** i `__NEXT_DATA__` har bare fargevarianten med
  `isSelected: true` reell pris — søsken-fargene i samme `products[]`-liste
  arver den viste fargens pris. `xxl_parser.py` skal kun emitte
  isSelected-varianten; dekning tapes ikke fordi `discovery.py` besøker hver
  fargevariants egen URL.
- **Felles signatur for begge:** mange tilbud i én butikk med identisk pris.
  `post_harvest_check.py` skal flagge enhver butikk der >80 % av tilbudene
  deler samme pris.
- **Re-split-vakten baseline-oppdaterer FØR den feiler** — en re-run etter rødt
  går derfor grønt uten at noe er fikset. Og «Re-run this job» i Actions kjører
  ORIGINAL-commiten; ny konfig krever ny workflow_dispatch.

## Verifisering etter endringer
- **Parser-/scraper-endringer:** når mulig, verifiser mot ekte markup via et
  probe-script (probe.yml) før full harvest. Etter harvest: sjekk
  `prislop.run_stats` (produkter ~870, tilbud ~3 300, stabile mellom kjøringer)
  og at butikken har mange distinkte priser med rimelig spenn.
- **Frontend-endringer:** sjekk at `?product=`, `?kategori=` og `?prisfall`
  ruter riktig både ved direkte lenke og fram/tilbake-navigasjon, at meta/
  canonical byttes per rute, og at all JSON-LD er gyldig JSON.
- **Sitemap:** `sitemap.xml` genereres av `generate_sitemap.py` i scrape.yml —
  rediger den aldri for hånd.

## Kontekst og arbeidsflyt
Prosjektbrief, prioriteringer og endringslogg vedlikeholdes i Notion-siden
«Prisløp — prosjektbrief»; oppsummer vesentlige endringer slik at de kan føres
inn der. Mennesket jobber primært fra iPhone/Safari — foretrekk små, avgrensede
endringer med tydelig beskrivelse av hva som må reviewes, én PR per tema.
