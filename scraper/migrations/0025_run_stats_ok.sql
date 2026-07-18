-- 0025: ok-flagg på run_stats — fiks for «re-run går grønt»-fella.
--
-- Bakgrunn (kjent feilsignatur i CLAUDE.md): post_harvest_check.py skrev
-- baseline-raden FØR den sammenlignet mot forrige kjøring. En rød kjøring
-- (|Δproducts| > toleranse) hadde derfor allerede flyttet baselinen, og en
-- re-run rett etterpå gikk grønt uten at noe var fikset.
--
-- Fiksen (kode + denne kolonnen): post_harvest_check.py kjører nå alle
-- sjekkene FØRST, sammenligner mot forrige kjøring der ok ikke var false
-- (gamle rader har ok = null og regnes som ok), og skriver først DERETTER
-- sin egen rad med utfallet. En rød kjøring flytter dermed aldri baselinen,
-- og re-run er rød til produkttallet faktisk er tilbake innenfor toleransen
-- av siste grønne kjøring.
--
-- Scriptet sjekker selv om kolonnen finnes og faller tilbake til gammel
-- oppførsel (med en advarsel) til denne migrasjonen er anvendt — trygt å
-- merge koden før migrasjonen er kjørt.

alter table prislop.run_stats add column if not exists ok boolean;

comment on column prislop.run_stats.ok is
  'Utfallet av post_harvest_check for denne kjøringen (null = før 0025, regnes som ok). Baseline-sammenligning bruker siste rad der ok is not false.';
