#!/usr/bin/env python3
"""
probe_olympia.py (v3) — finn produkt-URL-ene (ItemList/frekvens) + tile-markup.

v2 bommet: produkt-bilder er lazy (data-src), og første b-cdn.net var IE-banneret.
Theme = «Element» (nopCommerce). v3:
  1) JSON-LD ItemList på kategorisida -> produkt-URL-er rett ut (reneste).
  2) Frekvens-basert: interne 1-ledds-slugs (ekskl. nav) som opptrer >=2x = produkter.
  3) Rå-dump rundt data-productid / item-box / product-item -> ekte tile-struktur.
  4) Prober PDP-er fra funnene (JSON-LD/grid/select + EAN/kode).
Stdlib only. probe.yml (script=probe_olympia.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
from collections import Counter

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
LISTING = "/asfaltsko"

LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
HREF = re.compile(r'href="(/[a-z0-9%æøå][a-z0-9%æøå\-/]*)"', re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
CODE_RE = re.compile(r'/(\d{4}[a-z]\d{3})[_-]', re.I)
GRID_SPAN = re.compile(r'<span[^>]*class="[^"]*button-dropdown[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
SELECT = re.compile(r'<select\b.*?</select>', re.S | re.I)
NAV = {"sko","lopesko","asfaltsko","terrengsko","platesko","joggesko-dame","joggesko-herre",
       "saucony-endorphin-serien","lopeklar-2","tursko","fritidssko","arbeidssko","vernesko",
       "sandaler","kajakk","bekledning","sportsutstyr","ski","register","login","wishlist",
       "cart","asics","outlet","nyheter","blogg","s%c3%a5ler","havkajakk","surfski"}


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


def itemlist_urls(html):
    out = []
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") in ("ItemList", "CollectionPage"):
                for el in it.get("itemListElement") or []:
                    u = (el.get("url") if isinstance(el, dict) else None) or \
                        (el.get("item", {}).get("url") if isinstance(el, dict) and isinstance(el.get("item"), dict) else None)
                    if u:
                        out.append(u)
    return out


def freq_slugs(html):
    c = Counter()
    for h in HREF.findall(html):
        seg = h.strip("/").split("/")[0].lower()
        if "/" in h.strip("/"):
            continue                      # bare 1-ledds-slugs
        if seg and seg not in NAV and not seg.startswith(("register","login","cart","wishlist")):
            c[h] += 1
    return c


def dump_around(html, needle, n=700):
    i = html.lower().find(needle.lower())
    if i < 0:
        return None
    return re.sub(r"\s+", " ", html[max(0, i-120):i+n])


def probe_listing():
    print("=" * 78)
    print("A) PRODUKT-URL-er (/asfaltsko)")
    st, html = get(LISTING)
    print("  HTTP %s, %d B" % (st, len(html)))

    il = itemlist_urls(html)
    print("  JSON-LD ItemList-URL-er: %d" % len(il))
    for u in il[:6]:
        print("    ", u)

    c = freq_slugs(html)
    cands = [u for u, n in c.most_common() if n >= 2]
    print("  Frekvens-kandidater (>=2x, ekskl. nav): %d" % len(cands))
    for u in cands[:12]:
        print("     %2dx  %s" % (c[u], u))

    # rå tile-struktur
    for marker in ["data-productid", "item-box", "product-item", "producttitle", "product-title", "productGridProducts"]:
        seg = dump_around(html, marker)
        if seg:
            print("  --- rå markup rundt «%s» ---" % marker)
            print("  " + seg[:760])
            print("  --- slutt ---")
            break

    chosen = il or cands
    # normaliser til paths
    paths = []
    for u in chosen:
        p = u
        if u.startswith("http"):
            p = "/" + u.split("/", 3)[3] if u.count("/") >= 3 else u
        if p not in paths:
            paths.append(p)
    return paths[:3]


def probe_pdp(path):
    print("\n" + "-" * 78)
    print("PDP:", path)
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return
    ok = False
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") in ("Product", "ProductGroup"):
                ok = True
                off = it.get("offers") or {}
                if isinstance(off, list):
                    off = off[0] if off else {}
                hv = it.get("hasVariant") or []
                print("  JSON-LD %s: name=%r gtin=%s sku=%s price=%s avail=%s hasVariant=%d"
                      % (it.get("@type"), it.get("name"), it.get("gtin") or it.get("gtin13"),
                         it.get("sku"), off.get("price"), off.get("availability"), len(hv)))
                if hv and isinstance(hv[0], dict):
                    print("      variant[0]: size=%s gtin13=%s" % (hv[0].get("size"), hv[0].get("gtin13")))
    if not ok:
        print("  JSON-LD Product/ProductGroup: INGEN")
    gm = GRID_SPAN.search(html)
    if gm:
        hrefs = re.findall(r'href="([^"#?]+)"', gm.group(1))
        print("  [B1] button-dropdown-GRID: %d søsken-lenker" % len(hrefs))
        for h in hrefs[:6]:
            print("       ", h)
    sels = [s for s in SELECT.findall(html) if re.search(r"st\xf8rrelse|size|str\b", s, re.I)]
    if sels:
        opts = re.findall(r"<option[^>]*>(.*?)</option>", sels[0], re.S)
        print("  [B2] størrelses-SELECT: %d options" % len(opts))
        print("       ", " | ".join(re.sub(r"\s+", " ", o).strip() for o in opts[:12]))
    if not gm and not sels:
        seg = dump_around(html, "st\xf8rrelse", 1300)
        print("  rundt «Størrelse»:", (seg[:1300] if seg else "(ikke funnet)"))
    print("  EAN-kandidater:", sorted(set(EAN_RE.findall(html)))[:6] or "INGEN")
    print("  stilkode-kandidater:", sorted(set(CODE_RE.findall(html)))[:4] or "INGEN")


def main():
    print("probe_olympia v3 — ItemList/frekvens + tile-markup\n")
    pdps = probe_listing()
    print("\nB/C) PDP-INSPEKSJON")
    for p in pdps:
        probe_pdp(p)
    print("\nKONKLUSJON-HINT:")
    print("  ItemList eller frekvens-slugs gir produkt-URL-mønsteret for discovery.")
    print("  PDP: grid=B1(Brukås) | select=B2(inline) | hasVariant+gtin13=Foss-stil.")


if __name__ == "__main__":
    main()
