#!/usr/bin/env python3
"""
probe_bull_es.py (v5) — siste bit: paginering + per-storrelse lager.

found=262, rows_per_page=32, men &page=1 paginerte ikke. Vi:
  1) tester sidestorrelse-/offset-parametre for a hente alt,
  2) dumper size/skus/stock_source/in_stock/total_stock for ett produkt
     (avgjor om per-storrelse lager finnes i API-et -> da slipper vi PDP),
  3) teller hvor mange av treffene som er "Lopesko".
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
FACET = "/api/navigation/product?product_vendor%5B0%5D=13524&query="


def get(url):
    h = {"User-Agent": UA, "Accept": "application/json, */*"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def load(url):
    st, body = get(url)
    if st != 200 or not body:
        return None, []
    d = json.loads(body)
    items = d.get("items") if isinstance(d.get("items"), list) else \
        (d.get("result", {}).get("items", []) if isinstance(d.get("result"), dict) else [])
    return d, items


def id0(items):
    return items[0].get("id") if items else None


def main():
    print("probe_bull_es v5\n")
    d0, base_items = load(BASE + FACET)
    print("baseline: items=%d found=%s id[0]=%s\n" % (len(base_items), d0.get("found"), id0(base_items)))

    print("== sidestorrelse-/offset-parametre ==")
    for param in ["rows_per_page=300", "rows=300", "size=300", "limit=300",
                  "items_per_page=300", "page_size=300", "offset=32", "from=32",
                  "start=32", "page=2"]:
        d, items = load(BASE + FACET + "&" + param)
        if d is None:
            print("   %-18s -> feil" % param)
            continue
        moved = id0(items) != id0(base_items)
        print("   %-18s -> items=%-3d found=%s  id[0]%s" %
              (param, len(items), d.get("found"), " (NY!)" if moved else " (=side0)"))

    print("\n== per-storrelse-felt i ett produkt ==")
    if base_items:
        it = base_items[0]
        for f in ["title", "url", "schema_metatag_url", "color", "price", "list_price",
                  "on_sale", "in_stock", "total_stock", "size", "skus", "stock_source"]:
            print("   %-20s = %s" % (f, json.dumps(it.get(f), ensure_ascii=False)[:280]))

    print("\n== Lopesko-andel ==")
    lop = [it for it in base_items if "Løpesko" in (it.get("product_category_text") or [])]
    print("   av %d pa side 0 er %d Lopesko" % (len(base_items), len(lop)))


if __name__ == "__main__":
    main()
