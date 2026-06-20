#!/usr/bin/env python3
"""
probe_bull_es.py (v3) — inspiser /api/navigation/product-JSON-en.

GET /api/navigation/product gir 497KB JSON (hele katalogen). Vi vil vite:
  - strukturen (hvor ligger produkt-lista, hvor mange),
  - feltene per produkt: url/path, merke/vendor, kategori, kode/sku, pris,
    OG om varianter/storrelser/lager ligger inline (da slipper vi PDP-henting),
  - om query-string-facet (product_vendor=13524) filtrerer, ellers filtrerer vi
    sjolv i JSON-en.

Kjores i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"


def get(url, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json, */*", "Accept-Language": "nb-NO"}
    if headers:
        h.update(headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def biggest_list(obj):
    """Finn storste liste-av-dicts (sannsynlig produkt-array) + stien dit."""
    best = [None, []]
    def walk(o, p):
        if isinstance(o, list):
            if o and isinstance(o[0], dict) and len(o) > len(best[1]):
                best[0], best[1] = p, o
            for v in o[:2]:
                walk(v, p + "[]")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, p + "." + k)
    walk(obj, "")
    return best[0], best[1]


def main():
    print("probe_bull_es v3\n")
    for label, url in [("uten facet", BASE + "/api/navigation/product"),
                       ("med vendor-facet", BASE + "/api/navigation/product?product_vendor%5B0%5D=13524&query=")]:
        st, body = get(url)
        print("== %s -> %s, %dB ==" % (label, st, len(body)))
        if st != 200 or not body:
            continue
        try:
            d = json.loads(body)
        except Exception as e:
            print("   ikke JSON:", e, "| starter:", repr(body[:120]))
            continue
        if isinstance(d, dict):
            print("   topp-nokler:", list(d.keys())[:20])
        path, items = biggest_list(d)
        print("   produkt-array: '%s'  antall=%d" % (path, len(items)))
        if items:
            it = items[0]
            print("   felt i ett produkt:", list(it.keys()))
            # let etter interessante felt
            for probe_key in ["url", "path", "vendor", "brand", "category", "categories",
                              "sku", "code", "variation", "variations", "size", "sizes",
                              "stock", "price", "gtin", "ean", "title", "name"]:
                for k in it:
                    if probe_key in k.lower():
                        v = it[k]
                        vs = json.dumps(v, ensure_ascii=False)
                        print("     ~%-10s %s = %s" % (probe_key, k, vs[:160]))
                        break
        print()

    # ett fullt eksempelprodukt (untruncated-ish) fra uten-facet
    st, body = get(BASE + "/api/navigation/product")
    if st == 200:
        d = json.loads(body)
        _, items = biggest_list(d)
        # finn et Asics-produkt hvis mulig
        sample = items[0] if items else None
        for it in items:
            blob = json.dumps(it, ensure_ascii=False).lower()
            if "asics" in blob:
                sample = it
                break
        print("== ett (Asics-) eksempelprodukt, forste 2200 tegn ==")
        print(json.dumps(sample, ensure_ascii=False, indent=1)[:2200])


if __name__ == "__main__":
    main()
