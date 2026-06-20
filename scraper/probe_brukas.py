#!/usr/bin/env python3
"""
probe_brukas.py (v3) — hvordan ligger STORRELSENE pa en farge-side?

JSON-LD ga bare EN variant (storrelse 43,5) + tom hasVariant, og offer-URL hadde
size-suffiks (-435). Ser ut som nopCommerce grouped product. Vi dumper per-
storrelse-markupen pa farge-sida: data-productid, gtin-er, storrelse-etiketter,
pris og lagerstatus per rad. Tester ogsa om en size-variant-URL (-435) er egen side.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.brukas.no"
PROD = BASE + "/asics-gel-nimbus-28-herre"
LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def win(html, needle, n=4, pad=130):
    out, start, low = [], 0, html.lower()
    for _ in range(n):
        i = low.find(needle.lower(), start)
        if i < 0:
            break
        out.append(re.sub(r"\s+", " ", html[max(0, i - pad):i + len(needle) + pad]))
        start = i + len(needle)
    return out


def main():
    print("probe_brukas v3\n")
    st, p = get(PROD)
    print("== %s -> %s, %dB ==" % (PROD.replace(BASE, ""), st, len(p)))

    gtins = re.findall(r'"gtin"\s*:\s*"(\d{8,14})"', p) or re.findall(r'\b(\d{13})\b', p)
    print("gtin-er i sida: %d unike=%s" % (len(gtins), sorted(set(gtins))[:14]))
    pids = re.findall(r'data-productid="(\d+)"', p)
    print("data-productid: %d unike=%s" % (len(pids), sorted(set(pids))[:14]))
    for w in ["På lager", "Utsolgt", "Få på lager", "Ikke på lager", "in stock", "out of stock"]:
        c = p.lower().count(w.lower())
        if c:
            print("  lager-ord '%s': %d treff" % (w, c))

    print("\n-- alle JSON-LD Product-navn (ser vi flere storrelser?) --")
    for blk in LD.findall(p):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") == "Product":
                offs = it.get("offers")
                offs = offs if isinstance(offs, list) else [offs] if offs else []
                print("   name=%r" % it.get("name"))
                print("     gtin=%s  #offers=%d  hasVariant=%d" %
                      (it.get("gtin"), len(offs), len(it.get("hasVariant") or [])))

    print("\n-- markup rundt grouped/variant/size --")
    for anchor in ["product-variant", "variant-line", "associated", "grouped",
                   "attribute", "tbl", "product-grid", "data-productid"]:
        ws = win(p, anchor, n=1, pad=160)
        if ws:
            print("   [%s] ...%s..." % (anchor, ws[0]))

    print("\n-- inline JS-variantdata? (size + gtin/stock) --")
    for kw in ['"size"', "variants", "combinations", "stockquantity", "productvariant"]:
        for w in win(p, kw, n=1, pad=120):
            print("   [%s] ...%s..." % (kw, w))

    print("\n== size-variant-URL egen side? /asics-gel-nimbus-28-herre-435 ==")
    st2, p2 = get(BASE + "/asics-gel-nimbus-28-herre-435")
    print("   -> %s, %dB" % (st2, len(p2)))
    if st2 == 200:
        for blk in LD.findall(p2):
            try:
                d = json.loads(blk)
            except Exception:
                continue
            for it in (d if isinstance(d, list) else [d]):
                if isinstance(it, dict) and it.get("@type") == "Product":
                    print("   navn=%r gtin=%s" % (it.get("name"), it.get("gtin")))


if __name__ == "__main__":
    main()
