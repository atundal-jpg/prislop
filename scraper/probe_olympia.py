#!/usr/bin/env python3
"""
probe_olympia.py (v4) — riktig produkt-uttrekk + EKTE Asics-PDP-struktur.

Tile-struktur bekreftet (Element-theme, nopCommerce):
  <div class="product-item" data-productid="N">
    <div class="picture"><a href="/<merke>-<modell>-<farge>" title="Navn">
Produkt-URL = ren 1-ledds slug (merke-prefiks). v3 probet ved uhell merkesidene
(/aclima …) som lå øverst på frekvens. v4 trekker ut ekte produkt-tiles, filtrerer
til Asics, og prober Asics-PDP-er for struktur (B1 grid / B2 select / Foss-stil
hasVariant) + EAN + stilkode + per-størrelse-lager.

Sjekker også om /asics-produsentsida lister produktene (enkleste discovery-kilde)
vs. løpekategoriene (mikset merke, må filtreres til asics-).
Stdlib only. probe.yml (script=probe_olympia.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
ENUM = ["/asics", "/asfaltsko", "/terrengsko", "/platesko", "/joggesko-herre", "/joggesko-dame"]

# produkt-tile -> (href, title). Tolerant for whitespace mellom tagger.
TILE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"\s+title="([^"]*)"', re.I)
TILE_LOOSE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"\s+title="([^"]*)"', re.I | re.S)
PAGER = re.compile(r'[?&]pagenumber=(\d+)', re.I)
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
CODE_RE = re.compile(r'/(\d{4}[a-z]\d{3})[_-]', re.I)
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
    t = TILE.findall(html)
    if not t:
        t = TILE_LOOSE.findall(html)
    out = []
    for href, title in t:
        if (href, title) not in out:
            out.append((href, title))
    return out


def is_asics(href, title):
    return href.lower().startswith("/asics-") or "asics" in title.lower()


def enumerate_sources():
    print("=" * 78)
    print("A) ENUMERERING — riktig tile-uttrekk")
    asics_urls = []
    for path in ENUM:
        st, html = get(path)
        t = tiles(html)
        a = [(h, ti) for (h, ti) in t if is_asics(h, ti)]
        last = max([int(x) for x in PAGER.findall(html)] or [1])
        st2, html2 = get(path + "?pagenumber=2")
        new = len(set(tiles(html2)) - set(t))
        print("  %-18s HTTP %s | %3d tiles (%3d asics) | pager-max=%s | side2-nye=%d"
              % (path, st, len(t), len(a), last, new))
        for h, ti in a:
            if h not in [u for u, _ in asics_urls]:
                asics_urls.append((h, ti))
    print("  -- Asics-produkt-URL-er funnet totalt (unike): %d" % len(asics_urls))
    for h, ti in asics_urls[:8]:
        print("     %s  (%s)" % (h, ti))
    return [h for h, _ in asics_urls[:3]]


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
                print("  JSON-LD %s: name=%r gtin=%s sku=%s mpn=%s price=%s avail=%s hasVariant=%d"
                      % (it.get("@type"), it.get("name"), it.get("gtin") or it.get("gtin13"),
                         it.get("sku"), it.get("mpn"), off.get("price"), off.get("availability"), len(hv)))
                if hv and isinstance(hv[0], dict):
                    v0 = hv[0]
                    vo = v0.get("offers") or {}
                    if isinstance(vo, list):
                        vo = vo[0] if vo else {}
                    print("      variant[0]: size=%s gtin13=%s avail=%s" % (v0.get("size"), v0.get("gtin13"), vo.get("availability")))
    if not ok:
        print("  JSON-LD Product/ProductGroup: INGEN")

    # B1: grid m/ søsken-URL-er?
    gm = GRID_SPAN.search(html)
    if gm:
        hrefs = re.findall(r'href="([^"#?]+)"', gm.group(1))
        print("  [B1] button-dropdown-GRID: %d søsken-lenker" % len(hrefs))
        for h in hrefs[:6]:
            print("       ", h)

    # B2: størrelses-select / attributt? dump den ekte markupen
    size_sel = [s for s in SELECT.findall(html) if re.search(r"st\xf8rrelse|size|str\b|product_attribute", s, re.I)]
    if size_sel:
        opts = re.findall(r"<option[^>]*value=\"?(\d+)?\"?[^>]*>(.*?)</option>", size_sel[0], re.S)
        print("  [B2] størrelses-SELECT: %d options" % len(opts))
        print("       ", " | ".join(re.sub(r"\s+", " ", o[1]).strip() for o in opts[:14]))
    attr = re.search(r'class="attributes"[^>]*>(.*?)</dl>|class="attribute-squares"[^>]*>(.*?)</ul>', html, re.S | re.I)
    if attr:
        seg = re.sub(r"\s+", " ", (attr.group(1) or attr.group(2) or ""))
        print("  attributt-blokk (rå):", seg[:900])
    if not gm and not size_sel and not attr:
        i = html.lower().find("st\xf8rrelse")
        print("  rundt «Størrelse»:", re.sub(r"\s+", " ", html[max(0, i-100):i+1200])[:1200] if i >= 0 else "(ikke funnet)")

    print("  EAN-kandidater:", sorted(set(EAN_RE.findall(html)))[:8] or "INGEN")
    print("  stilkode-kandidater:", sorted(set(CODE_RE.findall(html)))[:4] or "INGEN")
    stock = {w: len(re.findall(w, html, re.I)) for w in ["på lager", "utsolgt", "ikke på lager", "in stock", "out of stock"]}
    print("  lager-ord:", {k: v for k, v in stock.items() if v})


def main():
    print("probe_olympia v4 — riktig tiles + ekte Asics-PDP\n")
    pdps = enumerate_sources()
    print("\nB/C) ASICS-PDP-INSPEKSJON")
    for p in pdps:
        probe_pdp(p)
    print("\nKONKLUSJON-HINT:")
    print("  Enumerering: bruk /asics hvis den lister alle; ellers løpekategoriene + asics-filter.")
    print("  PDP: grid=B1(Brukås) | select/attr=B2(inline) | hasVariant+gtin13=Foss-stil.")


if __name__ == "__main__":
    main()
