-- MAL/OPPSKRIFT for edisjonshale-merge (ikke kjørbar as-is — fyll inn
-- data-blokken før kjøring). Gjenbrukt mønster fra tidligere healer og
-- DQ-runde 3 (7. juli). Slår sammen et "hale"-produkt (src) inn i et
-- eksisterende kanonisk produkt (target, identifisert via ny match_key
-- eller brand+model+gender), flytter varianter/tilbud/prishistorikk,
-- repointer alert_events (FK uten cascade — må skje FØR sletting av
-- tilbud), løser kode-kollisjoner ved å flette variantene, og omdøper
-- produkter uten treff i stedet for å slette dem.
--
-- Bruk: erstatt data-blokken under med radene for denne rundens
-- edisjonshaler, kjør i Supabase, verifiser telling (products/offers via
-- prislop.run_stats), commit denne filen (med de faktiske verdiene som ble
-- kjørt) som dokumentasjon — ikke la den stå som uendret mal etter bruk.

do $$
declare
  r record;
  tgt uuid;
  v record;
begin
  for r in (
    values
      -- ('<src_product_id>'::uuid, '<nytt modellnavn>', '<kjønn>', '<merke>|<modell>|<kjønn>')
      ('00000000-0000-0000-0000-000000000000'::uuid, 'Eksempel Modell', 'herre', 'merke|eksempel modell|herre')
  ) as t(src_id, new_model, new_gender, new_key)
  loop
    select p.id into tgt from prislop.products p
      where p.match_key = r.new_key and p.id <> r.src_id limit 1;

    if tgt is null then
      select p.id into tgt from prislop.products p
        join prislop.products s on s.id = r.src_id
        where p.brand = s.brand and p.model = r.new_model
          and p.gender = r.new_gender and p.id <> r.src_id limit 1;
    end if;

    if tgt is not null then
      for v in
        select sv.id as sid, tv.id as tid
        from prislop.variants sv
        join prislop.variants tv
          on tv.product_id = tgt and tv.manufacturer_code = sv.manufacturer_code
        where sv.product_id = r.src_id and sv.manufacturer_code is not null
      loop
        -- repoint alert_events FØRST (FK uten cascade blokkerer ellers sletting)
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

      update prislop.variants set product_id = tgt where product_id = r.src_id;
      delete from prislop.products where id = r.src_id;
      update prislop.products set match_key = r.new_key
        where id = tgt and match_key <> r.new_key;
    else
      update prislop.products
         set model = r.new_model, gender = r.new_gender, match_key = r.new_key
       where id = r.src_id;
    end if;
  end loop;
end $$;

-- (Lagre denne filen som scraper/migrations/0003_edition_merge_template.sql i repoet.)
