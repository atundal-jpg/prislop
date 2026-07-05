#!/usr/bin/env python3
"""
probe_olympia.py (v5) — GO/NO-GO: bærer Olympia-PDP-er EAN + størrelser?

v4 avgjorde: Olympia fører i praksis ikke Asics (1 utsolgt pigg), og den ene
PDP-en manglet JSON-LD/EAN/størrelser — men produktet var utsolgt, så det kan
være falskt negativt. v5 tester ADIDAS (og Saucony som kontroll): enumererer
merkeprodukter fra løpekategoriene med det verifiserte tile-uttrekket, og
inspiserer PDP-er som er PÅ LAGER for: EAN/gtin, størrelses-struktur (grid/
select/attributter), artikkelkode, per-størrelse-lager.
GO = EAN + størrelser finnes -> Olympia inn i Adidas/Saucony-bølgen.
NO-GO = mangler broen -> stryk Olympia, Oslo Sportslager rykker opp.
Stdlib only. probe.yml (script=probe_olympia.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
CATS = ["/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame"]
BRANDS = ("adidas", "saucony")

TILE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"\s+title="([^"]*)"', re.I)
TILE_LOOSE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"\s+title="([^"]*)"', re.I | re.S)
PAGER = re.compile(r'[?&]pagenumber=(\d+)', re.I)
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
GRID_SPAN = re.compile(r'<span[^>]*class="[^"]*button-dropdown[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
SELECT = re.compile(r'<select\b.*?</select>', re.S | re.I)


def get(path):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def tiles(html):
    t = TILE.findall(html) or TILE_LOOSE.findall(html)
    out = []
    for h, ti in t:
        if (h, ti) not in out:
            out.append((h, ti))
    return out


def enumerate_brand(brand):
    found = []
    for cat in CATS:
        st, html = get(cat)
        last = min(max([int(x) for x in PAGER.findall(html)] or [1]), 4)
        pages = [html] + [get(f"{cat}?pagenumber={p}")[1] for p in range(2, last + 1)]
        for pg in pages:
            for h, ti in tiles(pg or ""):
                if h.lower().startswith(f"/{brand}-") and h not in [x for x, _ in found]:
                    found.append((h, ti))
    return found


def probe_pdp(path, title):
    print("\n" + "-" * 74)
    print("PDP: %s  (%s)" % (path, title))
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return False
    ok_ld = False
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") in ("Product", "ProductGroup"):
                ok_ld = True
                off = it.get("offers") or {}
                if isinstance(off, list):
                    off = off[0] if off else {}
                hv = it.get("hasVariant") or []
                print("  JSON-LD %s: name=%r gtin=%s sku=%s price=%s avail=%s hasVariant=%d"
                      % (it.get("@type"), it.get("name"), it.get("gtin") or it.get("gtin13"),
                         it.get("sku"), off.get("price"), off.get("availability"), len(hv)))
    if not ok_ld:
        print("  JSON-LD Product/ProductGroup: INGEN")

    gm = GRID_SPAN.search(html)
    if gm:
        hrefs = re.findall(r'href="([^"#?]+)"', gm.group(1))
        print("  [B1] button-dropdown-GRID: %d søsken-lenker" % len(hrefs))
        for h in hrefs[:6]:
            print("       ", h)
    sels = SELECT.findall(html)
    size_sel = [s for s in sels if re.search(r"st\xf8rrelse|size|str\b|attribute", s, re.I)]
    if size_sel:
        opts = re.findall(r"<option[^>]*>(.*?)</option>", size_sel[0], re.S)
        print("  [B2] størrelses-SELECT: %d options: %s" % (
            len(opts), " | ".join(re.sub(r"\s+", " ", o).strip() for o in opts[:14])))
    attr = re.search(r'class="attribute[s\-][^"]*"[^>]*>(.*?)</(?:dl|ul|div)>', html, re.S | re.I)
    if attr:
        print("  attributt-blokk (rå):", re.sub(r"\s+", " ", attr.group(1))[:800])
    if not gm and not size_sel and not attr:
        i = html.lower().find("st\xf8rrelse")
        print("  rundt «Størrelse»:", re.sub(r"\s+", " ", html[max(0, i-100):i+1200])[:1200] if i >= 0 else "(ikke funnet)")

    eans = sorted(set(EAN_RE.findall(html)))
    print("  EAN-kandidater (%d):" % len(eans), eans[:8] or "INGEN")
    stock = {w: len(re.findall(w, html, re.I)) for w in ["på lager", "utsolgt", "legg i handlekurv"]}
    print("  lager-ord:", {k: v for k, v in stock.items() if v})
    return bool(eans)


def main():
    print("probe_olympia v5 — GO/NO-GO på Adidas/Saucony-PDP-er (på lager)\n")
    verdict = {}
    for brand in BRANDS:
        print("=" * 74)
        found = enumerate_brand(brand)
        print("MERKE %s: %d produkter i løpekategoriene (side 1-4)" % (brand.upper(), len(found)))
        for h, ti in found[:6]:
            print("   ", h, "(%s)" % ti)
        got_ean = False
        for h, ti in found[:2]:
            got_ean = probe_pdp(h, ti) or got_ean
        verdict[brand] = (len(found), got_ean)
    print("\n" + "=" * 74)
    print("GO/NO-GO:")
    for b, (n, ean) in verdict.items():
        print("  %-8s: %3d produkter, EAN på PDP: %s -> %s"
              % (b, n, ean, "GO (integrerbar)" if (n and ean) else "NO-GO / mangler bro-data"))


if __name__ == "__main__":
    main()
