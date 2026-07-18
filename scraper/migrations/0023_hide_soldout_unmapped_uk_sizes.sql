-- 0023_hide_soldout_unmapped_uk_sizes.sql
--
-- BUG (rapportert 17. juli, skjermbilde fra mobil): størrelsesrutenettet
-- viser «UK 10 … UK 12 — utsolgt» som spøkelseschips ved siden av det
-- ordinære EU-settet. 449 slike chips fordelt på 90 produkter i dag.
--
-- ROTÅRSAK: v_prislop_sizes (EAN-broen) mapper butikk-native UK-labels
-- (numerisk < 30) til EU via (1) EAN-overlapp mot andre butikkers EU-rader
-- og (2) prislop.size_chart. Feiler begge, beholdes UK-labelen og frontend
-- viser «UK X» — bevisst og ærlig for KJØPBARE størrelser. Men UTSOLGTE
-- størrelser mangler som regel nettopp EAN i butikkens markup (ingen
-- kjøpbar variant → ingen EAN å lese), så det er systematisk de utsolgte
-- som ender umappet. Resultat: samme fysiske størrelse står ofte to ganger
-- (EU-raden + en umappet UK-tvilling), alltid som «utsolgt»-støy.
-- Berørte butikker i dag: Löplabbet (945 utsolgte UK-rader i rådata),
-- Intersport (375), Torshov (190 — samtlige utsolgt), Sport 1, Brukås.
-- (Ikke Olympia-butikken selv — men UK/EU-broen dette bygger på kom med
-- den implementeringen.)
--
-- FIKS: en rad som ETTER begge mappingforsøk fortsatt har UK-label OG er
-- utsolgt, filtreres ut av viewet. Begrunnelse: en utsolgt-chip sier
-- «denne størrelsen finnes, men er ikke tilgjengelig» — når vi ikke engang
-- kan si HVILKEN EU-størrelse det gjelder, er chipen ren støy. Kjøpbare
-- umappede UK-rader beholdes uendret (vises som «UK 8»; brukes også av
-- størrelsesfilteret og prisvarsler — send_alerts.py leser uansett kun
-- in_stock-rader, så den er upåvirket av filteret).
-- Kjent restproblem (bevisst uendret): en KJØPBAR umappet UK-chip kan
-- fortsatt dublere en EU-chip i rutenettet; den reelle løsningen der er
-- bedre size_chart-dekning, ikke filtrering.
--
-- MERK: v_prislop_sizes har til nå kun eksistert i databasen (ingen
-- migrasjonsfil i repoet). Denne filen etablerer definisjonen i repoet;
-- alt utenom det nye ytterste WHERE-filteret er identisk med
-- pg_get_viewdef-utskriften fra prod 17. juli.

create or replace view public.v_prislop_sizes as
with eu_map as (
  select
    offer_sizes.ean,
    mode() within group (order by offer_sizes.size_label) as eu_label
  from prislop.offer_sizes
  where offer_sizes.ean is not null
    and substring(offer_sizes.size_label, '^\d+(?:\.\d+)?')::numeric >= 30
    and substring(offer_sizes.size_label, '^\d+(?:\.\d+)?')::numeric <= 60
  group by offer_sizes.ean
),
mapped as (
  select
    va.product_id,
    os.size_label,
    st.name as store,
    va.color as colorway,
    os.ean,
    os.in_stock,
    os.stock_count,
    ofr.current_price as price,
    ofr.url,
    ofr.id as offer_id,
    btrim(replace(coalesce(
      case
        when substring(os.size_label, '^\d+(?:\.\d+)?')::numeric < 30
          then coalesce(m.eu_label, sc.eu_label)
        else null
      end, os.size_label), ',', '.')) as size
  from prislop.offer_sizes os
  join prislop.offers ofr on ofr.id = os.offer_id
  join prislop.variants va on va.id = ofr.variant_id
  join prislop.stores st on st.id = ofr.store_id
  join prislop.products pr on pr.id = va.product_id
  left join eu_map m on m.ean = os.ean
  left join prislop.size_chart sc
    on sc.brand = pr.brand
   and sc.store_slug = st.slug
   and (sc.gender is null or sc.gender = pr.gender)
   and sc.uk_label = replace(regexp_replace(os.size_label, '[Hh]$', '.5'), ',', '.')
  where ofr.last_seen_at > now() - interval '2 days'
)
select product_id, size_label, store, colorway, ean, in_stock, stock_count,
       price, url, offer_id, size
from mapped
-- 0023-filteret: fortsatt-UK-label (begge mappingforsøk feilet) + utsolgt
-- = spøkelseschip, ut. coalesce(..., true) holder ikke-numeriske labels
-- (substring gir NULL) inne uansett lagerstatus.
where in_stock
   or coalesce(substring(size, '^\d+(?:\.\d+)?')::numeric >= 30, true);

comment on view public.v_prislop_sizes is 'Størrelser per tilbud for frontend, EAN-bro-mappet: butikk-native UK-labels (<30) oversettes til EU via EAN-overlapp mot andre butikkers EU-rader, ellers prislop.size_chart; lykkes ingen av delene beholdes UK-labelen (frontend viser «UK X»). 0023: umappede UK-rader som OGSÅ er utsolgt filtreres ut — utsolgte størrelser mangler systematisk EAN (derav umappet), og en utsolgt-chip uten kjent EU-størrelse er ren støy som dublerer EU-settet. Kjøpbare umappede UK-rader beholdes (brukes av størrelsesfilter og prisvarsler; send_alerts leser kun in_stock-rader). Recency-filter: offers.last_seen_at siste 2 dager, som resten av leselaget.';

grant select on public.v_prislop_sizes to anon, authenticated;
