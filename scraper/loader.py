"""
loader.py — laster normaliserte butikkdata inn i `prislop`-schemaet i Supabase.

Designprinsipp: butikk-spesifikke parsere (xxl_parser, og senere feed-adaptere)
produserer en felles "OfferRecord"-struktur. Loaderen er butikk-agnostisk og
upserter hele kjeden idempotent, så den kan kjøres på hver skrap uten duplikater.

Kobling: direkte Postgres (psycopg2) via miljøvariabelen SUPABASE_DB_URL.
  - Til GitHub Actions: bruk Supabase "Connection pooling"-strengen (port 6543),
    lagret som hemmelig SUPABASE_DB_URL. (Settings → Database → Connection string.)
  - Krever: pip install psycopg2-binary

Felles OfferRecord (ett objekt per butikk × fargevariant):
{
  "store":   {"slug","name","source","network"},   # source: 'scrape'|'feed'
  "brand", "model", "gender",                       # gender: herre|dame|unisex|barn
  "product_line", "category",
  "color", "manufacturer_code", "image_url",
  "store_sku", "url", "currency", "price",
  "sizes": [ {"size_label","ean","in_stock","stock_count"}, ... ],
}
"""

from __future__ import annotations
import os
import psycopg2
import psycopg2.extras

import normalize  # matching-/normaliseringshjernen (kanonisk produkt + fargevei)

# Skrapede butikkbilder er opphavsrettslig vernet og kan ikke gjenbrukes uten
# lisens. Hold dette AV til bildene kommer fra en affiliate-feed som gir
# bruksrett; da byttes kilden og denne settes True (eller fjernes).
STORE_SCRAPED_IMAGES = False


# ---------------------------------------------------------------------------
#  Tilkobling
# ---------------------------------------------------------------------------
def get_conn():
    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise RuntimeError("Sett SUPABASE_DB_URL (Supabase connection string).")
    return psycopg2.connect(dsn)


# ---------------------------------------------------------------------------
#  Upserts — én funksjon per nivå. Alle returnerer id-en de rørte.
# ---------------------------------------------------------------------------
def upsert_store(cur, store: dict) -> int:
    cur.execute(
        """
        insert into prislop.stores (slug, name, source, network)
        values (%(slug)s, %(name)s, %(source)s, %(network)s)
        on conflict (slug) do update
            set name = excluded.name,
                source = excluded.source,
                network = excluded.network,
                active = true
        returning id
        """,
        {"slug": store["slug"], "name": store["name"],
         "source": store.get("source", "scrape"), "network": store.get("network")},
    )
    return cur.fetchone()[0]


def upsert_product(cur, rec: dict) -> str:
    # Rens modellnavnet: trekk ut kjønn som har lekket inn i navnet (overstyrer
    # da butikkens kjønnsfelt), og lag et pent visningsnavn. Match-nøkkelen
    # bygges på det RENSEDE navnet + korrigert kjønn, så samme sko forenes
    # selv om butikkene skriver det rotete ("GEL-NIMBUS 27", "...Dame Grå/Sølv").
    cleaned_model, name_gender = normalize.split_model_gender(rec["model"])
    gender = name_gender or rec["gender"]
    display_model = normalize.canonical_model(rec["model"])
    bk, mk, gk = normalize.product_key(rec["brand"], cleaned_model, gender)
    match_key = f"{bk}|{mk}|{gk}"
    brand = normalize.norm_brand(rec["brand"])
    line = rec.get("product_line")
    category = rec.get("category", "running")

    # 1) Autoritativ merge på match_key — forener samme sko på tvers av butikker,
    #    også når visningsnavnet skrives ulikt ("Nimbus 28" vs "Gel-Nimbus 28").
    cur.execute("select id from prislop.products where match_key = %s", (match_key,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "update prislop.products set product_line = coalesce(%s, product_line), "
            "category = %s where id = %s",
            (line, category, row[0]),
        )
        return row[0]

    # 2) Fall tilbake på den harde unik-nøkkelen (brand, model, gender). Fanger
    #    tilfeller der canonical_model (visningsnavn) og norm_model (match_key) er
    #    UENIGE — da finnes raden allerede, men med en annen match_key, og en ren
    #    INSERT ville krasjet på unik-constrainten og veltet HELE butikkens lasting.
    #    Vi gjenbruker raden og løfter den til den ferske, kanoniske match_key-en
    #    (selvhelbredende — nøkkelen er ledig siden steg 1 ikke fant den).
    cur.execute(
        "select id from prislop.products where brand = %s and model = %s and gender = %s",
        (brand, display_model, gender),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "update prislop.products set match_key = %s, "
            "product_line = coalesce(%s, product_line), category = %s where id = %s",
            (match_key, line, category, row[0]),
        )
        return row[0]

    # 3) Nytt produkt.
    cur.execute(
        """
        insert into prislop.products (brand, model, gender, product_line, category, match_key)
        values (%s, %s, %s, %s, %s, %s)
        returning id
        """,
        (brand, display_model, gender, line, category, match_key),
    )
    return cur.fetchone()[0]

def get_or_create_variant(cur, product_id: str, rec: dict) -> str:
    """Kanonisk fargevei: nøkles på produsentkode -> EAN-overlapp -> ny.
    Butikkens eget fargenavn lever på tilbudet (offers.store_color), ikke her,
    slik at samme sko ikke splittes fordi butikkene navngir fargen ulikt."""
    code = rec.get("manufacturer_code")
    eans = [s.get("ean") for s in rec.get("sizes", []) if s.get("ean")]
    img = rec.get("image_url") if STORE_SCRAPED_IMAGES else None

    # 1) match på produsentkode (Asics-kode)
    if code:
        cur.execute(
            "select id from prislop.variants where product_id = %s and manufacturer_code = %s limit 1",
            (product_id, code),
        )
        row = cur.fetchone()
        if row:
            cur.execute("update prislop.variants set image_url = coalesce(%s, image_url) where id = %s",
                        (img, row[0]))
            return row[0]

    # 2) match på EAN-overlapp blant produktets varianter (broer kodeløse butikker)
    if eans:
        cur.execute(
            """
            select distinct v.id from prislop.variants v
            join prislop.offers o on o.variant_id = v.id
            join prislop.offer_sizes os on os.offer_id = o.id
            where v.product_id = %s and os.ean = any(%s)
            limit 1
            """,
            (product_id, eans),
        )
        row = cur.fetchone()
        if row:
            vid = row[0]
            if code:   # arve produsentkode hvis vi nå kjenner den og varianten mangler den
                cur.execute(
                    "update prislop.variants set manufacturer_code = %s where id = %s and manufacturer_code is null",
                    (code, vid),
                )
            cur.execute("update prislop.variants set image_url = coalesce(%s, image_url) where id = %s",
                        (img, vid))
            return vid

    # 3) ny fargevei (kanonisk farge = butikkens navn ved første observasjon)
    cur.execute(
        "insert into prislop.variants (product_id, color, manufacturer_code, image_url) "
        "values (%s, %s, %s, %s) returning id",
        (product_id, rec.get("color"), code, img),
    )
    return cur.fetchone()[0]


def upsert_offer(cur, store_id: int, variant_id: str, rec: dict, run_ts=None) -> tuple[str, bool]:
    """Upserter tilbudet og fører prishistorikk KUN når prisen er ny/endret.
    Returnerer (offer_id, accepted). accepted=False når samme (butikk, variant)
    alt er sett i DENNE kjøringen med lavere/lik pris — da hopper vi over
    recorden. Skjer når én butikk har TO artikkelnumre for samme fysiske
    colorway (XXL: gammel artikkel på klarering + ny sesongartikkel, samme
    EAN-er, funnet 5. juli: 57 tilbud flip-floppet 289/729 i prishistorikken).
    Vi beholder deterministisk det BILLIGSTE av duplikatene."""
    cur.execute(
        "select id, current_price, last_seen_at from prislop.offers "
        "where store_id = %s and variant_id = %s",
        (store_id, variant_id),
    )
    existing = cur.fetchone()
    price = rec.get("price")
    currency = rec.get("currency", "NOK")
    any_stock = any(s.get("in_stock") for s in rec.get("sizes", []))

    if existing:
        offer_id, old_price, last_seen = existing
        if (run_ts is not None and last_seen is not None and last_seen >= run_ts
                and price is not None and old_price is not None
                and float(price) >= float(old_price)):
            return offer_id, False           # dyrere duplikat i samme kjøring
        cur.execute(
            """
            update prislop.offers
               set store_sku = %s, url = %s, currency = %s, store_color = %s,
                   current_price = %s, in_stock = %s, last_seen_at = now()
             where id = %s
            """,
            (rec.get("store_sku"), rec["url"], currency, rec.get("color"),
             price, any_stock, offer_id),
        )
        price_changed = price is not None and price != old_price
    else:
        cur.execute(
            """
            insert into prislop.offers
                (store_id, variant_id, store_sku, url, currency, store_color, current_price, in_stock)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (store_id, variant_id, rec.get("store_sku"), rec["url"],
             currency, rec.get("color"), price, any_stock),
        )
        offer_id = cur.fetchone()[0]
        price_changed = price is not None

    if price_changed:
        # Same-run-idempotent: aksepteres en BILLIGERE duplikat-record senere i
        # samme kjøring (XXL-dobbeltartikler), skal kjøringens history-rad
        # ERSTATTES, ikke suppleres — ellers får historikken et falskt hopp
        # (729 -> 289) innen samme tx (28 tilbud i kjøringen 5. juli 17:36Z).
        if run_ts is not None:
            cur.execute(
                "delete from prislop.price_history where offer_id = %s and observed_at >= %s",
                (offer_id, run_ts),
            )
        cur.execute(
            "insert into prislop.price_history (offer_id, price, currency) values (%s, %s, %s)",
            (offer_id, price, currency),
        )
    return offer_id, True


def upsert_sizes(cur, offer_id: str, sizes: list[dict]) -> int:
    psycopg2.extras.execute_batch(
        cur,
        """
        insert into prislop.offer_sizes (offer_id, size_label, ean, in_stock, stock_count, updated_at)
        values (%s, %s, %s, %s, %s, now())
        on conflict (offer_id, size_label) do update
            set ean = excluded.ean,
                in_stock = excluded.in_stock,
                stock_count = excluded.stock_count,
                updated_at = now()
        """,
        [(offer_id, s["size_label"], s.get("ean"),
          s.get("in_stock", False), s.get("stock_count")) for s in sizes],
    )
    return len(sizes)


def mark_unseen_stale(cur, store_id: int, run_ts) -> int:
    """Flagg tilbud (og størrelser) som IKKE ble sett i denne kjøringen som
    utgått, for ÉN butikk.

    «Ikke sett» = last_seen_at eldre enn kjøringens transaksjonstid. now() er
    konstant i en transaksjon, så alt vi rørte i denne kjøringen fikk
    last_seen_at = run_ts; alt som er eldre forsvant fra butikkens liste.

    Vi SLETTER ikke — bare setter in_stock=false — så prishistorikk og et evt.
    comeback bevares (dukker varianten opp igjen, gjenåpner upsert_offer den).
    Kun den oppgitte butikken berøres; kilder som ikke er med i denne kjøringen
    (f.eks. den avviklede Get Inspired-raden) står helt urørt.

    Returnerer antall tilbud som ble flagget utgått i denne kjøringen.
    """
    cur.execute(
        """
        update prislop.offer_sizes os
           set in_stock = false, updated_at = now()
          from prislop.offers o
         where os.offer_id = o.id
           and o.store_id = %s
           and o.last_seen_at < %s
           and os.in_stock = true
        """,
        (store_id, run_ts),
    )
    cur.execute(
        """
        update prislop.offers
           set in_stock = false
         where store_id = %s
           and last_seen_at < %s
           and in_stock = true
        """,
        (store_id, run_ts),
    )
    return cur.rowcount


# ---------------------------------------------------------------------------
#  Orkestrering
# ---------------------------------------------------------------------------
def load(offers: list[dict]) -> dict:
    """Laster en liste OfferRecords i én transaksjon. Returnerer enkel statistikk.

    run_pipeline kaller denne ÉN gang per butikk, så stale-flagging nedenfor
    gjelder kun den butikken vi nettopp lastet. En butikk som feiler (0 records)
    kaller aldri load(), så en forbigående fetch-feil kan aldri nulle en butikk.
    """
    stats = {"offers": 0, "sizes": 0, "stale": 0}
    conn = get_conn()
    try:
        with conn:                       # commit/rollback-transaksjon
            with conn.cursor() as cur:
                cur.execute("select now()")   # transaksjonstid = «sett i denne kjøringen»
                run_ts = cur.fetchone()[0]
                store_ids: dict[str, int] = {}
                for rec in offers:
                    slug = rec["store"]["slug"]
                    if slug not in store_ids:
                        store_ids[slug] = upsert_store(cur, rec["store"])
                    product_id = upsert_product(cur, rec)
                    variant_id = get_or_create_variant(cur, product_id, rec)
                    offer_id, accepted = upsert_offer(cur, store_ids[slug], variant_id, rec, run_ts)
                    if not accepted:
                        continue             # dyrere duplikat-artikkel i samme kjøring
                    stats["sizes"] += upsert_sizes(cur, offer_id, rec.get("sizes", []))
                    stats["offers"] += 1
                # Etter at alt er upsertet: flagg det vi IKKE så denne kjøringen
                # (forsvunne fargevarianter) som utgått — per butikk, aldri andre.
                for sid in store_ids.values():
                    stats["stale"] += mark_unseen_stale(cur, sid, run_ts)
                # NB (5. juli, kveld): skala-normalisering av størrelses-labels
                # skjer i LESELAGET (public.v_prislop_sizes, EAN-bro i viewen) —
                # aldri her. Skrivetids-omdøping slåss mot re-harvest (parseren
                # emitter rå labels på nytt -> spøkelsespar) og blandet-skala-
                # grids finnes legitimt (Intersport: EU + UK 14.5/15/16).
    finally:
        conn.close()
    return stats


def xxl_to_offers(parse_result: dict) -> list[dict]:
    rows = parse_result["rows"]
    by_variant: dict[str, dict] = {}
    for r in rows:
        key = r["style_code"]                       # én fargevariant
        if key not in by_variant:
            model = (r["model_title"] or "").split(",")[0].strip() or r["model_title"]
            by_variant[key] = {
                "store": {"slug": "xxl", "name": "XXL", "source": "scrape", "network": None},
                "brand": r["brand"],
                "model": model,                     # "Gel-Nimbus 27"
                "gender": (r["gender"] or "").lower() or "unisex",
                "product_line": r["product_line"],
                "category": "running",
                "color": r["color"],
                "manufacturer_code": None,          # XXL eksponerer ikke Asics-koden
                "image_url": None,
                "store_sku": r["style_code"],
                "url": r["url"],
                "currency": r["currency"],
                "price": r["price"],
                "sizes": [],
            }
        by_variant[key]["sizes"].append({
            "size_label": r["size_label"],
            "ean": r["ean"],
            "in_stock": (r["online_status"] != "OUTOFSTOCK"),
            "stock_count": r["online_stock"],
        })
    return list(by_variant.values())


if __name__ == "__main__":
    import sys
    import xxl_parser

    path = sys.argv[1] if len(sys.argv) > 1 else "Document_-_1246154_1_Style.txt"
    parsed = xxl_parser.parse_xxl(open(path, encoding="utf-8").read())
    offers = xxl_to_offers(parsed)
    print(f"Adaptert {len(offers)} tilbud fra XXL-siden.")
    stats = load(offers)
    print(f"Lastet: {stats['offers']} tilbud, {stats['sizes']} størrelser.")
