#!/usr/bin/env python3
"""
probe_olympia_dryrun.py — kjører den EKTE discovery.discover() + olympia_parser
mot live sider (ingen DB-skriving) for å verifisere hele kjeden før en faktisk
harvest. Kjøres via probe.yml (script=probe_olympia_dryrun.py). psycopg2
stubbes (discovery.py -> loader-importen trenger den, men vi kaller den aldri).
"""
from __future__ import annotations
import sys
import types

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import urllib.request
import discovery


class Fetcher:
    def __init__(self, *a, **k):
        pass

    def get(self, url):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (prislop-probe)", "Accept-Language": "nb-NO"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"    fetch-feil {url}: {e}")
            return None


def main():
    print("probe_olympia_dryrun — ekte discovery + olympia_parser, ingen DB-skriving\n")
    fetcher = Fetcher()
    adapter = discovery.STORES["olympia"]["adapter"]

    for brand in ("adidas", "saucony"):
        print("=" * 74)
        print("MERKE:", brand.upper())
        urls = discovery.discover(fetcher, "olympia", brand, "", limit=1000)
        print(f"  discovery: {len(urls)} produkt-URL-er")

        ok, bad, no_stock, no_price = 0, 0, 0, 0
        for i, url in enumerate(urls):
            html = fetcher.get(url)
            if not html:
                print(f"    FETCH-FEIL {url}")
                bad += 1
                continue
            try:
                recs = adapter(html, url)
            except Exception as e:
                print(f"    PARSE-FEIL {url}: {e}")
                bad += 1
                continue
            if not recs:
                print(f"    INGEN RECORD (parser returnerte None) {url}")
                bad += 1
                continue
            rec = recs[0]
            n_sizes = len(rec["sizes"])
            n_in_stock = sum(1 for s in rec["sizes"] if s["in_stock"])
            if n_in_stock == 0:
                no_stock += 1
            if rec["price"] is None:
                no_price += 1
            ok += 1
            if i < 6 or rec["price"] is None or n_in_stock == 0:
                print(f"    OK  {rec['brand']} | {rec['model']} | {rec['gender']} | {rec['color']!r}")
                print(f"        kode={rec['manufacturer_code']} sku={rec['store_sku']} "
                      f"pris={rec['price']} {rec['currency']} str={n_sizes} (på lager={n_in_stock})")
                print(f"        {[s['size_label'] for s in rec['sizes']]}")
        print(f"  -> {ok} OK, {bad} feil/tomme, {no_stock} med 0 på lager, "
              f"{no_price} med pris=None (av {len(urls)} totalt)")

    print("\n" + "=" * 74)
    print("Ingenting skrevet til databasen — kun parse-verifisering.")


if __name__ == "__main__":
    main()
