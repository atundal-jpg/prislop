#!/usr/bin/env python3
"""
probe_olympia.py — kartlegg Olympia Sport (olympiasport.no) for discovery+parser.

Plattform bekreftet: nopCommerce (meta-generator), server-rendret — SAMME familie
som Brukås. Slug-kategorier (/lopesko, /asfaltsko, /terrengsko, /platesko,
/joggesko-dame|herre) + /asics-produsentliste. CDN olympiasport.b-cdn.net.

Det proben må avgjøre (skriv IKKE discovery/parser før dette):
  A) ENUMERERING: gir /asics (produsent) eller løpekategoriene produkt-URL-ene?
     Paginerer de med ?pagenumber=N? Hvor mange Asics-sko?
  B) PDP-STRUKTUR — den store forgreningen:
     (B1) Brukås-stil: én URL = én (farge+størrelse), med et størrelses-GRID av
          søsken-URL-er  -> gjenbruk mønster: parse per størrelse + aggregate().
     (B2) Standard nopCommerce: én URL = én colorway med størrelses-DROPDOWN/
          attributter inline (alle størrelser på én side) -> enklere inline-parser.
  C) Har PDP per-størrelse-lager + EAN/gtin + Asics-stilkode (for bro-kobling)?

Stdlib only. Kjøres via .github/workflows/probe.yml (script=probe_olympia.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
# produsentliste + et par løpekategorier som enumererings-kandidater
LISTINGS = ["/asics", "/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame"]

TITLE_A = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
ANY_PROD_A = re.compile(r'<a[^>]*href="(/[a-z0-9][^"#?]*asics[^"#?]*)"', re.I)
PAGER = re.compile(r'[?&]pagenumber=(\d+)', re.I)
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
CODE_RE = re.compile(r'/(\d{4}[a-z]\d{3})[_-]', re.I)
# Brukås-stil grid?  /  attributt-dropdown?
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


def section(html, needle, before=120, after=1600):
    i = html.lower().find(needle.lower())
    if i < 0:
        return ""
    return re.sub(r"\s+", " ", html[max(0, i - before):i + after])


def enumerate_listings():
    print("=" * 78)
    print("A) ENUMERERING")
    best = []
    for path in LISTINGS:
        st, html = get(path)
        titles = list(dict.fromkeys(TITLE_A.findall(html)))
        if not titles:                       # fallback: alle asics-lenker
            titles = list(dict.fromkeys(ANY_PROD_A.findall(html)))
        last = max([int(x) for x in PAGER.findall(html)] or [1])
        # test paginering
        st2, html2 = get("%s?pagenumber=2" % path)
        t2 = list(dict.fromkeys(TITLE_A.findall(html2) or ANY_PROD_A.findall(html2)))
        new = len(set(t2) - set(titles))
        print("  %-20s HTTP %s | %3d produkt-lenker | pager-max=%s | side2 nye=%d"
              % (path, st, len(titles), last, new))
        if len(titles) > len(best):
            best = titles
    for u in best[:6]:
        print("    eks:", u)
    return best[:3]


def probe_pdp(path):
    print("\n" + "-" * 78)
    print("PDP:", path)
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return

    # JSON-LD
    types = []
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type"):
                t = it.get("@type")
                types.append(t)
                if t in ("Product", "ProductGroup"):
                    off = it.get("offers") or {}
                    if isinstance(off, list):
                        off = off[0] if off else {}
                    print("  JSON-LD %s: name=%r gtin=%s sku=%s price=%s avail=%s hasVariant=%s"
                          % (t, it.get("name"), it.get("gtin") or it.get("gtin13"),
                             it.get("sku"), off.get("price"), off.get("availability"),
                             len(it.get("hasVariant") or []) if it.get("hasVariant") else 0))
    if not types:
        print("  JSON-LD: INGEN")

    # B1 vs B2: grid av søsken-URL-er, eller dropdown/select inline?
    gm = GRID_SPAN.search(html)
    if gm:
        hrefs = re.findall(r'href="([^"#?]+)"', gm.group(1))
        print("  [B1?] button-dropdown-GRID funnet: %d lenker (Brukås-stil søsken-URL-er)" % len(hrefs))
        for h in hrefs[:6]:
            print("        ", h)
    sels = SELECT.findall(html)
    size_sel = [s for s in sels if re.search(r"st\xf8rrelse|size|str\b", s, re.I)]
    if size_sel:
        opts = re.findall(r"<option[^>]*>(.*?)</option>", size_sel[0], re.S)
        print("  [B2?] størrelses-SELECT funnet: %d options (inline størrelser)" % len(opts))
        print("        ", " | ".join(re.sub(r"\s+", " ", o).strip() for o in opts[:10]))
    if not gm and not size_sel:
        print("  Verken grid eller size-select tydelig — dumper rundt «Størrelse»:")
        print("   ", section(html, "st\xf8rrelse")[:1200])

    # bro-data
    print("  EAN-kandidater:", sorted(set(EAN_RE.findall(html)))[:6] or "INGEN")
    print("  Asics-stilkode-kandidater:", sorted(set(CODE_RE.findall(html)))[:4] or "INGEN")


def main():
    print("probe_olympia v1 — nopCommerce (samme familie som Brukås)\n")
    pdps = enumerate_listings()
    print("\nB/C) PDP-INSPEKSJON")
    for p in pdps:
        probe_pdp(p)
    print("\nKONKLUSJON-HINT:")
    print("  * button-dropdown-grid m/ søsken-URL-er -> B1: gjenbruk Brukås (parse per str + aggregate).")
    print("  * størrelses-select m/ alle størrelser inline -> B2: enkel inline-parser (én PDP = colorway).")
    print("  * JSON-LD hasVariant[] m/ gtin13 -> som Foss (per-str EAN rett fra JSON-LD).")


if __name__ == "__main__":
    main()
