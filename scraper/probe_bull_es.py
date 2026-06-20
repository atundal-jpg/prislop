#!/usr/bin/env python3
"""
probe_bull_es.py (v4) — inspiser produkt-itemsene i /api/navigation/product.

Topp-nokler: result, context, facets, items, found, more, rows_per_page, rows.
Produktene ligger i 'items' (eller result.items). Vi dumper found/rows_per_page/
more, ett fullt produkt (alle felt: url, merke, kategori, kode, pris, varianter,
storrelser, lager), og tester paginering (&page=1).
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
FACET = "/api/navigation/product?product_vendor%5B0%5D=13524&query="


def get(url):
    h = {"User-Agent": UA, "Accept": "application/json, */*", "Accept-Language": "nb-NO"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def items_of(d):
    if isinstance(d.get("items"), list):
        return d["items"]
    res = d.get("result")
    if isinstance(res, dict) and isinstance(res.get("items"), list):
        return res["items"]
    return []


def summarize(label, url):
    st, body = get(url)
    print("== %s -> %s, %dB ==" % (label, st, len(body)))
    if st != 200 or not body:
        return None
    d = json.loads(body)
    for k in ("found", "rows_per_page", "more", "rows"):
        if k in d:
            print("   %s = %s" % (k, json.dumps(d[k])[:80]))
    items = items_of(d)
    print("   items: %d" % len(items))
    return d, items


def main():
    print("probe_bull_es v4\n")
    res = summarize("Asics-facet side 0", BASE + FACET)
    if not res:
        return
    d, items = res
    if items:
        it = items[0]
        print("\n== felt i ett produkt ==")
        print("  ", list(it.keys()))
        print("\n== fullt produkt (forste 2600 tegn) ==")
        print(json.dumps(it, ensure_ascii=False, indent=1)[:2600])

    # paginering
    print("\n== paginering ==")
    _, body2 = get(BASE + FACET + "&page=1")
    if body2:
        d2 = json.loads(body2)
        it2 = items_of(d2)
        first0 = json.dumps(items[0], ensure_ascii=False)[:80] if items else ""
        first1 = json.dumps(it2[0], ensure_ascii=False)[:80] if it2 else ""
        print("   side1 items=%d  side1[0]!=side0[0]: %s" % (len(it2), first0 != first1))

    # kategori-facet: finn lopesko-IDen til filtrering
    print("\n== kategori-facets (for a finne lopesko-ID) ==")
    facets = (d.get("facets") or {})
    if isinstance(facets, dict):
        for fname, fval in facets.items():
            its = fval.get("items") if isinstance(fval, dict) else None
            if its and any("sko" in (x.get("name", "").lower()) for x in its if isinstance(x, dict)):
                print("   facet '%s':" % fname)
                for x in its[:20]:
                    if isinstance(x, dict):
                        print("      %s (key=%s, count=%s)" % (x.get("name"), x.get("search_key"), x.get("count")))


if __name__ == "__main__":
    main()
