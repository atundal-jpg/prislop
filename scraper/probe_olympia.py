#!/usr/bin/env python3
"""
probe_olympia.py (v2) — knekk produkt-lenke-mønster + PDP-struktur.

v1: nopCommerce bekreftet, paginering finnes (/asfaltsko=7 sider, /joggesko-*=5,
/terrengsko=3), MEN produkt-lenkene ble ikke fanget (ingen `product-title`-klasse;
slug uten «asics»). v2 dumper ekte listing-markup, trekker ut produkt-URL-ene via
BILDE-ankeret (robust uansett klasse), og prober PDP-er.

Avgjør: produkt-URL-mønster + paginering (A), og PDP-struktur (B1 Brukås-grid vs
B2 nopCommerce størrelses-select vs JSON-LD hasVariant) + EAN/kode (C).
Stdlib only. probe.yml (script=probe_olympia.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
LISTING = "/asfaltsko"   # 7 sider — flest løpesko

# produkt-tile: et anker som omslutter et produkt-bilde (CDN). Robust mot klasse.
IMG_A = re.compile(r'<a\s+href="(/[^"#?]+)"[^>]*>\s*(?:<picture\b|<img\b)', re.I)
CDN_A = re.compile(r'<a\s+href="(/[^"#?]+)"[^>]*>(?:(?!</a>).)*?b-cdn\.net', re.I | re.S)
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
CODE_RE = re.compile(r'/(\d{4}[a-z]\d{3})[_-]', re.I)
GRID_SPAN = re.compile(r'<span[^>]*class="[^"]*button-dropdown[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
SELECT = re.compile(r'<select\b.*?</select>', re.S | re.I)
NAV = {"sko","lopesko","asfaltsko","terrengsko","platesko","joggesko-dame",
       "joggesko-herre","saucony-endorphin-serien","lopeklar-2","tursko","fritidssko",
       "arbeidssko","vernesko","sandaler","kajakk","bekledning","sportsutstyr","ski",
       "register","login","wishlist","cart","asics","outlet","nyheter","blogg"}


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


def product_urls(html):
    urls = []
    for rx in (IMG_A, CDN_A):
        for h in rx.findall(html):
            seg = h.strip("/").split("/")[0].split("?")[0]
            if seg and seg not in NAV and h not in urls:
                urls.append(h)
    return urls


def probe_listing():
    print("=" * 78)
    print("A) LISTING-MARKUP + PRODUKT-LENKER (/asfaltsko)")
    st, html = get(LISTING)
    print("  HTTP %s, %d B" % (st, len(html)))

    # dump rå markup rundt første produkt-bilde (avslører tile-strukturen)
    m = re.search(r"b-cdn\.net", html)
    if m:
        a = html.rfind("<a", max(0, m.start() - 600), m.start())
        seg = html[a if a >= 0 else m.start() - 400:m.start() + 200]
        print("  --- rå tile rundt første produkt-bilde ---")
        print("  " + re.sub(r"\s+", " ", seg)[:900])
        print("  --- slutt ---")

    urls = product_urls(html)
    print("  produkt-URL-er (via bilde-anker): %d" % len(urls))
    for u in urls[:8]:
        print("    ", u)

    # paginering: side 2 gir nye?
    st2, html2 = get(LISTING + "?pagenumber=2")
    u2 = product_urls(html2)
    print("  side 2: %d produkt-URL-er, %d nye vs side 1" % (len(u2), len(set(u2) - set(urls))))
    return urls[:3]


def probe_pdp(path):
    print("\n" + "-" * 78)
    print("PDP:", path)
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return
    found_ld = False
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") in ("Product", "ProductGroup"):
                found_ld = True
                off = it.get("offers") or {}
                if isinstance(off, list):
                    off = off[0] if off else {}
                hv = it.get("hasVariant") or []
                print("  JSON-LD %s: name=%r gtin=%s sku=%s price=%s avail=%s hasVariant=%d"
                      % (it.get("@type"), it.get("name"),
                         it.get("gtin") or it.get("gtin13"), it.get("sku"),
                         off.get("price"), off.get("availability"), len(hv)))
                if hv and isinstance(hv[0], dict):
                    v = hv[0]
                    print("      variant[0]: size=%s gtin13=%s avail=%s"
                          % (v.get("size"), v.get("gtin13"),
                             ((v.get("offers") or {}) if not isinstance(v.get("offers"), list) else {}).get("availability")))
    if not found_ld:
        print("  JSON-LD Product/ProductGroup: INGEN")

    gm = GRID_SPAN.search(html)
    if gm:
        hrefs = re.findall(r'href="([^"#?]+)"', gm.group(1))
        print("  [B1] button-dropdown-GRID: %d søsken-lenker (Brukås-stil)" % len(hrefs))
        for h in hrefs[:6]:
            print("       ", h)
    sels = [s for s in SELECT.findall(html) if re.search(r"st\xf8rrelse|size|str\b", s, re.I)]
    if sels:
        opts = re.findall(r"<option[^>]*>(.*?)</option>", sels[0], re.S)
        print("  [B2] størrelses-SELECT: %d options inline" % len(opts))
        print("       ", " | ".join(re.sub(r"\s+", " ", o).strip() for o in opts[:12]))
    if not gm and not sels:
        i = html.lower().find("st\xf8rrelse")
        print("  Verken grid eller select — rundt «Størrelse»:")
        print("   ", re.sub(r"\s+", " ", html[max(0, i-100):i+1400])[:1400] if i >= 0 else "(ikke funnet)")

    print("  EAN-kandidater:", sorted(set(EAN_RE.findall(html)))[:6] or "INGEN")
    print("  stilkode-kandidater:", sorted(set(CODE_RE.findall(html)))[:4] or "INGEN")


def main():
    print("probe_olympia v2 — produkt-lenker + PDP-struktur\n")
    pdps = probe_listing()
    print("\nB/C) PDP-INSPEKSJON")
    for p in pdps:
        probe_pdp(p)
    print("\nKONKLUSJON-HINT:")
    print("  B1 grid m/ søsken-URL-er -> gjenbruk Brukås (parse per str + aggregate).")
    print("  B2 size-select inline   -> enkel inline-parser (én PDP = colorway).")
    print("  JSON-LD hasVariant+gtin13 -> som Foss (per-str EAN rett fra JSON-LD).")


if __name__ == "__main__":
    main()
