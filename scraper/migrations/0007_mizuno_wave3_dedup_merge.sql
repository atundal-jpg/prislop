-- Kjørt i Supabase 9. juli 2026 (KS-oppfølging, funn 1: Mizuno-duplikater).
--
-- PROBLEM: Sport 1/Intersport skriver kjønnssuffiks i selve modellnavnet
-- («Wave Horizon 9(M)» / «(W)» / «(U)») og tidvis merkeprefiks («Mizuno Neo
-- Vista 2»). Det ga 19 dupegrupper der samme sko/kjønn fantes som 2–4
-- separate produkter — prissammenligningen fragmentert, produkttallet
-- kunstig høyt. Rot-årsaken er fikset i normalize.py samme dag (strip av
-- parentes-suffiks + mizuno/brooks/new balance som lead-tokens); denne
-- filen dokumenterer engangs-oppryddingen av eksisterende data.
--
-- MERGE-LOGIKK (samme mønster som 0003-malen):
--   * Kanonisk nøkkel: lower(model) - parentes-kjønnssuffiks - merkeprefiks.
--   * Target = eldste produkt (min created_at) per (brand, nøkkel, gender).
--   * prislop.alerts repekes FØR sletting — alerts.product_id har ON DELETE
--     CASCADE, så uten repeking ville brukernes prisvarsler blitt slettet
--     i stillhet. (Viktigste fellen i hele operasjonen.)
--   * Kodekollisjoner (samme manufacturer_code under begge) flettes:
--     alert_events repekes, duplikat-tilbud/priser/størrelser slettes,
--     resterende tilbud repekes, src-variant slettes.
--   * Solo-produkter med stygg navneform men uten ren tvilling (16 stk)
--     ble RENAMET til ren form + ny match_key — ellers ville neste harvest
--     med ny normalize.py opprettet rene tvillinger og gjenskapt splitten.
--   * initcap-bivirkning «Gtx» -> «GTX» rettet til slutt.
--
-- RESULTAT (verifisert):
--   * 896 -> 870 produkter (26 merget bort; Mizuno 91 -> 65).
--   * 0 gjenværende dupegrupper, 0 foreldreløse varianter,
--     alle 3 brukervarsler intakt.
--
-- NB FOR NESTE HARVEST: Δproducts vil vise ca. -26 mot baseline 896 →
-- re-split-vakten trigges. Kjør neste harvest manuelt via workflow_dispatch
-- med resplit_tolerance=50 (input eksponert i scrape.yml samme dag), ELLER
-- la den feile én gang (vakten baseline-oppdaterer før den feiler) og re-run.
--
-- Selve DO-blokken som ble kjørt:

do $$
declare
  g record;
  s record;
  v record;
begin
  for g in (
    with canon as (
      select id, brand, model, gender, created_at,
        trim(regexp_replace(regexp_replace(regexp_replace(lower(model),
          '\(\s*(m|w|u)\s*\)', ' ', 'g'),
          '^(mizuno|new balance|brooks) ', ''),
          '\s+', ' ', 'g')) as ckey
      from prislop.products
      where brand in ('Mizuno','Brooks','New Balance')
    )
    select brand, ckey, gender,
           (array_agg(id order by created_at))[1] as target_id,
           (array_agg(id order by created_at))[2:] as src_ids
    from canon
    group by brand, ckey, gender
    having count(*) > 1
  )
  loop
    update prislop.products
       set model = initcap(g.ckey),
           match_key = lower(g.brand) || '|' || g.ckey || '|' || g.gender
     where id = g.target_id;

    for s in (select unnest(g.src_ids) as src_id)
    loop
      update prislop.alerts set product_id = g.target_id where product_id = s.src_id;

      for v in
        select sv.id as sid, tv.id as tid
        from prislop.variants sv
        join prislop.variants tv
          on tv.product_id = g.target_id and tv.manufacturer_code = sv.manufacturer_code
        where sv.product_id = s.src_id and sv.manufacturer_code is not null
      loop
        update prislop.alert_events ae
           set offer_id = t.id
          from prislop.offers o
          join prislop.offers t
            on t.variant_id = v.tid and t.store_id = o.store_id
         where ae.offer_id = o.id and o.variant_id = v.sid;

        delete from prislop.price_history where offer_id in (
          select o.id from prislop.offers o where o.variant_id = v.sid
            and exists (select 1 from prislop.offers t
                        where t.variant_id = v.tid and t.store_id = o.store_id));
        delete from prislop.offer_sizes where offer_id in (
          select o.id from prislop.offers o where o.variant_id = v.sid
            and exists (select 1 from prislop.offers t
                        where t.variant_id = v.tid and t.store_id = o.store_id));
        delete from prislop.offers o where o.variant_id = v.sid
            and exists (select 1 from prislop.offers t
                        where t.variant_id = v.tid and t.store_id = o.store_id);
        update prislop.offers set variant_id = v.tid where variant_id = v.sid;
        delete from prislop.variants where id = v.sid;
      end loop;

      update prislop.variants set product_id = g.target_id where product_id = s.src_id;
      delete from prislop.products where id = s.src_id;
    end loop;
  end loop;
end $$;

-- Etterrydding (også kjørt):
update prislop.products
   set model = initcap(trim(regexp_replace(regexp_replace(regexp_replace(lower(model),
         '\(\s*(m|w|u)\s*\)', ' ', 'g'),
         '^(mizuno|new balance|brooks) ', ''),
         '\s+', ' ', 'g'))),
       match_key = lower(brand) || '|' || trim(regexp_replace(regexp_replace(regexp_replace(lower(model),
         '\(\s*(m|w|u)\s*\)', ' ', 'g'),
         '^(mizuno|new balance|brooks) ', ''),
         '\s+', ' ', 'g')) || '|' || gender
 where model ~* '\((m|w|u)\)$' or model ~* '^(mizuno|new balance|brooks) ';

update prislop.products set model = regexp_replace(model, '\mGtx\M', 'GTX', 'g') where model ~ '\mGtx\M';
