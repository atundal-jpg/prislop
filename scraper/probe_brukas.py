#!/usr/bin/env python3
"""
probe_brukas.py (v2) — las discovery + parser for Brukas (nopCommerce).

1) Discovery: er /asics en ekte Asics-produsentside? (sammenlign med fake-slug)
   Virker ?manufacturerids=169 server-side pa kategoriene?
2) Parser: dump JSON-LD pa en produktside -> har variantene pris + lager (og
   hvordan er storrelse kodet)? Hvor ligger hovedprisen?
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
from urllib.parse import urljoin

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.brukas.no"
PROD_TITLE = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
PAGENUM = re.compile(r'[?&]pagenumber=(\d+)', re.I)
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


def slugs(html):
    out, seen = [], set()
    for m in PROD_TITLE.finditer(html):
        u = urljoin(BASE, m.group(1)).replace(BASE, "")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main():
    print("probe_brukas v2\n")

    print("== 1a) /asics ekte? (vs fake-slug) ==")
    for path in ["/asics", "/asics?pagenumber=2", "/asics-fake-xyz-123", "/joggesko-herre?manufacturerids=169"]:
        st, html = get(BASE + path)
        sl = slugs(html)
        pages = sorted(set(int(x) for x in PAGENUM.findall(html)))
        asics = [s for s in sl if s.startswith("/asics-")]
        print("   %-38s -> %s  prod=%2d  asics-slug=%2d  maxpage=%s" %
              (path, st, len(sl), len(asics), pages[-1] if pages else "-"))
        if "asics" in path and "fake" not in path and sl:
            print("        eksempler:", sl[:4])

    print("\n== 1b) manufacturerids=169 pa lopekategoriene ==")
    for cat in ["/joggesko-dame", "/joggesko-herre", "/terrengsko-dame", "/terrengsko-herre"]:
        st, html = get("%s%s?manufacturerids=169" % (BASE, cat))
        sl = slugs(html)
        asics = [s for s in sl if s.startswith("/asics-")]
        pages = sorted(set(int(x) for x in PAGENUM.findall(html)))
        print("   %-22s -> prod=%2d (asics-slug=%2d) maxpage=%s" %
              (cat, len(sl), len(asics), pages[-1] if pages else "-"))

    print("\n== 2) produktside JSON-LD + pris ==")
    st, p = get(BASE + "/asics-gel-nimbus-28-herre")
    print("   status=%s lengde=%d" % (st, len(p)))
    blocks = LD.findall(p)
    print("   JSON-LD-blokker:", len(blocks))
    for i, blk in enumerate(blocks):
        try:
            d = json.loads(blk)
        except Exception as e:
            print("   [%d] ikke-parsebar (%s): %s" % (i, e, blk[:120]))
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            print("   [%d] @type=%s nokler=%s" % (i, t, list(it.keys())))
            if t in ("Product", "ProductGroup"):
                print("       ", json.dumps(it, ensure_ascii=False)[:1600])
            off = it.get("offers")
            if off:
                offs = off if isinstance(off, list) else [off]
                print("        offers(%d):" % len(offs))
                for o in offs[:3]:
                    if isinstance(o, dict):
                        print("          ", json.dumps(o, ensure_ascii=False)[:260])
    # hovedpris i HTML
    for m in re.finditer(r'(price-value-\d+|product-price|prices)[^>]*>([^<]{1,30})', p, re.I):
        print("   pris-markup:", m.group(0)[:90])
    pv = re.search(r'\b(\d[\d \u00a0.]{1,7}),-', p)
    print("   forste ',-'-pris:", pv.group(0) if pv else "?")


if __name__ == "__main__":
    main()
