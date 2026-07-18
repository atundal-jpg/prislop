-- 0017_price_history_stock_columns.sql
--
-- OPPGAVE 1 (prisfall-robusthet, del 1 av 3): begynn å lagre lagerstatus i
-- prishistorikken. I dag inneholder prislop.price_history KUN (offer_id,
-- price, currency, observed_at) — in_stock finnes bare som et NÅ-øyeblikksbilde
-- på prislop.offers/offer_sizes, aldri som en tidsserie. Vi kan derfor ikke i
-- dag svare på "var denne prisen kjøpbar for 10 dager siden", og hver dag uten
-- den registreringen er historikk vi aldri får tilbake — prishistorikken er
-- kjerneproduktet vårt.
--
-- Ren utvidelse: to nye, NULL-bare kolonner. NULL = ukjent, gjelder all
-- historikk fram til denne migrasjonen kjøres (og for enhver rad skrevet av en
-- ikke-oppdatert loader). Ingen eksisterende kolonner røres, ingen eksisterende
-- rad endres, ingenting brekker. Alle views som leser price_history skal
-- behandle NULL som "ukjent", ALDRI som "utsolgt" — en pris vi ikke vet
-- lagerstatusen til er fortsatt en reell, historisk pris (se 0019-kommentaren
-- for hvordan drop14 bruker dette).
--
-- sizes_in_stock lagres i tillegg til in_stock (som dekker "var NOE av
-- tilbudet på lager") for å bevare mer signal for eventuell fremtidig bruk
-- (f.eks. "nesten utsolgt"-vekting) uten at vi trenger enda en migrasjon den
-- dagen noen vil bruke det.
--
-- MERK (grense loaderen ikke løser): prislop.price_history får kun en ny rad
-- når PRISEN endrer seg (se loader.py, upsert_offer — uendret av denne saken).
-- Det betyr at de nye feltene fanger lagerstatus PÅ TIDSPUNKTET FOR EN
-- PRISENDRING, ikke en kontinuerlig daglig lagerhistorikk — går et tilbud tomt
-- uten at prisen endrer seg, får vi ingen ny rad som viser det. Dette er en
-- bevisst, minimal utvidelse (ingen endring i når price_history skrives, kun
-- hva som skrives når den skrives) — en fullverdig daglig lagerhistorikk ville
-- kreve å endre skrive-kadensen for price_history, som er en mye større
-- endring med konsekvenser for fremover-fyllingen i v_prislop_price_series
-- (0004/0006/0018) og er ikke del av denne saken.

alter table prislop.price_history
  add column if not exists in_stock boolean,
  add column if not exists sizes_in_stock integer;

comment on column prislop.price_history.in_stock is 'Lagerstatus (minst én størrelse på lager) på observasjonstidspunktet. NULL = ukjent (all historikk før 0017, eller loader uten støtte) — skal ALDRI tolkes som utsolgt. Kun satt fra og med denne migrasjonen, og kun når raden skrives (dvs. ved prisendring, se loader.py).';
comment on column prislop.price_history.sizes_in_stock is 'Antall størrelser på lager på observasjonstidspunktet. NULL = ukjent, samme regel som in_stock.';
