"""
run_pipeline.py — orkestrerer høstingen av løpesko inn i prislop-basen.

For hver butikk × målmodell: discovery -> produkt-URL-er -> hent -> parse ->
samle OfferRecords -> last via loader. Robust per butikk (én butikk som feiler
velter ikke resten) og per produkt (én side som feiler hopper vi over).

Kjøres i GitHub Actions med SUPABASE_DB_URL som hemmelig miljøvariabel.

Skalerings-notat: dette gjør discovery + prisinnhenting i samme kjøring. Når
katalogen vokser, splitt gjerne i to jobber — sjelden discovery (finn nye
produkter) og hyppig prisoppdatering (kun kjente URL-er) — for å spare kall.
"""

from __future__ import annotations
import os
import sys

import discovery
import loader
from fetch import Fetcher

BRAND = "Asics"
STORES = ["xxl", "torshov", "intersport"]   # de feed-løse butikkene

MODELS = [
    "Gel-Nimbus 27", "Nimbus 28", "Nimbus 28 ATC",
    "Glideride Max", "Glideride Max 2",
    "Sonicblast", "Megablast", "Superblast 2", "Superblast 3",
    "Gel-Kayano 32", "Gel-Kayano 33",
    "Magic Speed 4", "Magic Speed 5",
    "Fujispeed 4", "MetaFuji Trail",
    "Trabuco MT GTX", "Trabuco Max 4", "Trabuco Max 5",
    "Trabuco 13 GTX", "Trabuco 14 GTX",
    "GT-2000 14", "GT-2000 14 TR",
    "Novablast 5", "Novablast 5 ATC",
    "MetaSpeed Edge Tokyo", "MetaSpeed Sky Tokyo",
    "Gel-FujiSetsu 3 GTX", "FujiSetsu Max GTX", "Fuji Lite 6",
]

PRODUCTS_PER_MODEL = 6          # tak på fargevarianter per modell per butikk


def harvest_store(fetcher, slug: str) -> list[dict]:
    records, seen = [], set()
    for model in MODELS:
        try:
            urls = discovery.discover(fetcher, slug, BRAND, model, limit=PRODUCTS_PER_MODEL)
        except Exception as e:
            print(f"  [{slug}] discovery-feil «{model}»: {e}")
            continue
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            html = fetcher.get(url)
            if not html:
                continue
            try:
                records.extend(discovery.STORES[slug]["adapter"](html, url))
            except Exception as e:
                print(f"  [{slug}] parse-feil {url}: {e}")
    return records


def main():
    if not os.environ.get("SUPABASE_DB_URL"):
        sys.exit("Mangler SUPABASE_DB_URL (sett den som hemmelighet i Actions).")

    fetcher = Fetcher()
    grand = {"offers": 0, "sizes": 0}

    for slug in STORES:
        name = discovery.STORES[slug]["name"]
        print(f"\n=== {name} ===")
        records = harvest_store(fetcher, slug)
        produkter = len({(r.get("brand"), r.get("model"), r.get("color")) for r in records})
        print(f"  fant {len(records)} tilbud / ~{produkter} fargevarianter")

        if not records:
            # Null treff = nesten alltid feil søke-URL/markør, ikke tom butikk.
            print(f"  ⚠️  NULL treff for {name} — verifiser search_url/marker_re i discovery.py")
            continue

        try:
            stats = loader.load(records)
            grand["offers"] += stats["offers"]
            grand["sizes"] += stats["sizes"]
            print(f"  lastet {stats['offers']} tilbud, {stats['sizes']} størrelser")
        except Exception as e:
            print(f"  ❌ lasting feilet for {name}: {e}")

    print(f"\nTOTALT lastet: {grand['offers']} tilbud, {grand['sizes']} størrelser")


if __name__ == "__main__":
    main()
