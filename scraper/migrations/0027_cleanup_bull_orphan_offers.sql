-- 0027: rydd bort foreldreløse Bull-tilbud (rad-multiplisering 18.–27. juli).
--
-- IKKE ANVENDT ENNÅ. Skal kjøres FØRST etter at parser-/loader-fiksen har
-- kjørt én harvest og akseptansetest 1 er grønn (0 ferske Bull-tilbud med
-- store_sku IS NULL). Kjøres den før, regenereres radene ved neste harvest.
-- Migrasjonen håndhever dette selv — se VAKT 1 og 2 under.
--
-- BAKGRUNN
-- discovery.by_brand fikk Saucony, adidas og Kiprun i PR #18 uten at
-- bull_parser lærte kodeformatene deres. store_sku ble NULL for de merkene,
-- og siden Bull hverken har produsentkode eller per-størrelse EAN i markupen
-- sto loaderen igjen uten nøkkel: ny variant + nytt tilbud ved HVER kjøring.
-- Målt 27. juli: 6 597 Bull-rader mot 663 distinkte URL-er, +155 per harvest,
-- og v_prislop_offers (2-døgnsvindu = ca. 8 harvester) viste opptil 8
-- duplikater per fargevariant — Saucony Triumph 23 herre sto med Bull 64
-- ganger (8 ekte farger × 8 duplikater), alle 1 610 kr.
--
-- SCOPING
--   butikk = bull
--   AND store_sku IS NULL          -- radene loaderen aldri kunne nøkle
--   AND ikke nyeste rad per url    -- én rad per URL overlever alltid
--   AND ikke referert av alert_events   -- varselhistorikk røres aldri
--
-- «Ingen offer_sizes» er BEVISST ikke tatt med som AND-vilkår: loaderen
-- skriver størrelser for hver duplikatrad den lager, så bare 2 av 5 931
-- kandidatrader har tom offer_sizes. Et AND der ville gjort migrasjonen til
-- en no-op. «Ikke nyeste rad per url» er det vilkåret som faktisk skiller
-- duplikat fra original, og det garanterer alene at ingen URL mister sin
-- siste rad. offer_sizes og price_history følger med via ON DELETE CASCADE.
--
-- SELECT-FORHÅNDSSVAR (kjørt mot prod 27. juli, før fiksen har kjørt):
--
--   with newest as (
--     select distinct on (o.url) o.id
--     from prislop.offers o join prislop.stores s on s.id = o.store_id
--     where s.slug = 'bull'
--     order by o.url, o.last_seen_at desc nulls last, o.id desc)
--   select count(*) from prislop.offers o
--   join prislop.stores s on s.id = o.store_id
--   where s.slug = 'bull' and o.store_sku is null
--     and o.id not in (select id from newest);
--
--   -> 5 931 tilbud   (av 6 597 Bull-rader; 666 blir stående)
--      5 929 price_history-rader   (av 18 065 totalt = 33 %)
--     69 468 offer_sizes-rader
--          0 alert_events-rader berørt
--          1 clicks-rad (offer_id settes til null av eksisterende FK)
--
-- Tallene er ferskvare: de faktiske slettetallene rapporteres av RAISE NOTICE
-- når migrasjonen kjøres, og vil være noe lavere etter at fiksen har kjørt en
-- harvest (rader som får store_sku igjen faller ut av settet).

begin;

-- VAKT 1+2: er fiksen faktisk i drift?
do $$
declare
    n_fresh int;
    n_fresh_nullsku int;
begin
    select count(*),
           count(*) filter (where o.store_sku is null)
      into n_fresh, n_fresh_nullsku
      from prislop.offers o
      join prislop.stores s on s.id = o.store_id
     where s.slug = 'bull'
       and o.last_seen_at > now() - interval '12 hours';

    if n_fresh = 0 then
        raise exception 'Ingen ferske Bull-tilbud siste 12 t — harvesten har '
            'ikke kjørt. Avbryter: opprydding skal skje rett etter en '
            'vellykket harvest med den nye parseren, ikke på gammel tilstand.';
    end if;

    if n_fresh_nullsku > 10 then
        raise exception 'Akseptansetest 1 er ikke grønn: % av % ferske '
            'Bull-tilbud står fortsatt uten store_sku. Parser-/loader-fiksen '
            'har ikke kjørt en harvest ennå — radene ville blitt regenerert '
            'med en gang. Avbryter.', n_fresh_nullsku, n_fresh;
    end if;

    raise notice 'Ferske Bull-tilbud: % (uten store_sku: %)', n_fresh, n_fresh_nullsku;
end $$;

-- Kandidatene, plukket ut én gang så sletting og rapport ser samme sett.
create temporary table _bull_orphans on commit drop as
with newest_per_url as (
    select distinct on (o.url) o.id
      from prislop.offers o
      join prislop.stores s on s.id = o.store_id
     where s.slug = 'bull'
     order by o.url, o.last_seen_at desc nulls last, o.id desc
)
select o.id, o.variant_id
  from prislop.offers o
  join prislop.stores s on s.id = o.store_id
 where s.slug = 'bull'
   and o.store_sku is null
   and o.id not in (select id from newest_per_url)
   and not exists (select 1 from prislop.alert_events ae where ae.offer_id = o.id);

do $$
declare
    n_offers int;
    n_hist int;
    n_sizes int;
    n_left int;
begin
    select count(*) into n_offers from _bull_orphans;
    select count(*) into n_hist from prislop.price_history ph
     where ph.offer_id in (select id from _bull_orphans);
    select count(*) into n_sizes from prislop.offer_sizes os
     where os.offer_id in (select id from _bull_orphans);
    select count(*) into n_left from prislop.offers o
      join prislop.stores s on s.id = o.store_id
     where s.slug = 'bull' and o.id not in (select id from _bull_orphans);

    raise notice 'Sletter % Bull-tilbud (% price_history, % offer_sizes via '
        'cascade). Bull-rader som blir stående: %.',
        n_offers, n_hist, n_sizes, n_left;
end $$;

-- price_history og offer_sizes følger med (ON DELETE CASCADE);
-- clicks.offer_id settes til null (ON DELETE SET NULL) og statistikken består.
delete from prislop.offers o
 using _bull_orphans d
 where o.id = d.id;

-- Variantene duplikatene pekte på står nå uten tilbud. Vi sletter KUN de som
-- er helt tomme etter slettingen over — en variant kan deles med andre
-- butikker, og de skal ikke røres.
with tomme as (
    select distinct d.variant_id
      from _bull_orphans d
     where not exists (select 1 from prislop.offers o where o.variant_id = d.variant_id)
)
delete from prislop.variants v
 using tomme t
 where v.id = t.variant_id;

commit;

-- ETTERKONTROLL (kjør manuelt etterpå):
--   -- 1) ingen foreldreløse igjen
--   select count(*) from prislop.offers o join prislop.stores s on s.id=o.store_id
--    where s.slug='bull' and o.store_sku is null;
--   -- 2) én rad per URL hos Bull blant de ferske
--   select count(*) as tilbud, count(distinct url) as urler
--     from prislop.offers o join prislop.stores s on s.id=o.store_id
--    where s.slug='bull' and o.last_seen_at > now() - interval '12 hours';
--   -- 3) DEKNING SKAL IKKE FALLE: begge tallene over skal være >= 816 / >= 663.
