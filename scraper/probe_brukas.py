#!/usr/bin/env python3
"""
probe_brukas.py (v4) — avgjør A vs B for Brukås størrelses-grid.

Hva v4 svarer på:
  1) Hvordan ser RÅ-markupen rundt størrelses-gridet ut (container + klasser)?
  2) Koder gridet per-størrelse-lager inline (utsolgt/disabled/sold-out-klasse)?
        JA  -> fiks A mulig: les hele størrelses-raden fra ÉN side, 0 ekstra kall
        NEI -> fiks B: hent hver søsken-størrelses-side for lager (~650 kall)
  3) Hva er selektoren / felles colorway-prefiks for søsken-URL-ene?
  4) Bekreft at søsken-sider har egen JSON-LD (availability + gtin/EAN).

Slik leser du loggen:
  - Se på «RÅ grid-region»: hvilken container/klasse omslutter størrelses-
    lenkene, og har utsolgte størrelser en egen klasse?
  - «<<...>>» bak en størrelse = utsolgt-/disabled-ord funnet i ankeret -> A mulig.
  - Ingen slike markører + alle størrelser ser like ut -> B (hent per side).
  - SØSKEN-SJEKK viser at hver størrelse er egen side med egen availability+gtin.

Stdlib only. Kjøres via .github/workflows/probe.yml (script=probe_brukas.py),
working-directory: scraper.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.brukas.no"

# 3 colorways av SAMME modell (samme nopCommerce-mal => selektor generaliserer).
# -445-2 var på lager i forrige probe; -herre / -herre-3 er to andre colorways.
SEEDS = [
    "/asics-gel-nimbus-28-herre-445-2",
    "/asics-gel-nimbus-28-herre",
    "/asics-gel-nimbus-28-herre-3",
]

LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I)

# Anker hvis synlige tekst er en størrelses-etikett: 7H, 41,5, 42, 44,5 ...
SIZE_A = re.compile(
    r'<a\b[^>]*href="([^"#?]+)"[^>]*>\s*'
    r'([0-9]{1,2}(?:[.,][0-9])?H?)\s*</a>', re.I)

SOLD_WORDS = ["utsolgt", "sold-out", "soldout", "out-of-stock", "outofstock",
              "unavailable", "not-available", "ikke-tilgjengelig", "ikke tilgjengelig",
              "disabled", "oos", "notify", "restock", "tomt", "ikke p\u00e5 lager"]


def get(path):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def ld_product(html):
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") == "Product":
                return it
    return None


def common_prefix(paths):
    if not paths:
        return ""
    s1, s2 = min(paths), max(paths)
    k = 0
    while k < len(s1) and k < len(s2) and s1[k] == s2[k]:
        k += 1
    return s1[:k]


def largest_cluster(matches, gap=800):
    """Finn den tetteste klyngen av størrelses-ankre = selve gridet
    (filtrerer bort tilfeldige numerisk-merkede lenker andre steder)."""
    if not matches:
        return []
    matches = sorted(matches, key=lambda m: m[0])
    clusters, cur = [], [matches[0]]
    for m in matches[1:]:
        if m[0] - cur[-1][1] <= gap:
            cur.append(m)
        else:
            clusters.append(cur)
            cur = [m]
    clusters.append(cur)
    return max(clusters, key=len)


def anchor_around(html, idx):
    """Hent hele <a ...>...</a> som omslutter posisjon idx (for klasse-innsyn)."""
    a = html.rfind("<a", 0, idx)
    b = html.find("</a>", idx)
    if a < 0 or b < 0:
        return ""
    return re.sub(r"\s+", " ", html[a:b + 4])


def probe_one(path):
    print("\n" + "=" * 78)
    print("COLORWAY:", path)
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return []

    p = ld_product(html)
    if p:
        off = p.get("offers") or {}
        if isinstance(off, list):
            off = off[0] if off else {}
        print("  JSON-LD: name=%r" % p.get("name"))
        print("           gtin=%s  price=%s  availability=%s  sku=%s"
              % (p.get("gtin"), off.get("price"),
                 off.get("availability"), p.get("sku") or p.get("mpn")))
    else:
        print("  JSON-LD Product: INGEN")

    matches = [(m.start(1), m.end(), m.group(1), m.group(2))
               for m in SIZE_A.finditer(html)]
    grid = largest_cluster([(s, e, h, l) for (s, e, h, l) in matches])
    if not grid:
        print("  INGEN størrelses-ankre funnet (SIZE_A bommet) — dumper rundt 'Størrelse':")
        i = html.lower().find("st\u00f8rrelse")
        if i >= 0:
            print(re.sub(r"\n\s*\n", "\n", html[i - 80:i + 2500])[:3000])
        return []

    start = max(0, grid[0][0] - 300)
    end = min(len(html), grid[-1][1] + 300)
    region = html[start:end]
    print("  --- RÅ grid-region (%d tegn, %d størrelses-ankre) ---"
          % (len(region), len(grid)))
    print(re.sub(r"\n\s*\n", "\n", region)[:4200])
    print("  --- slutt grid-region ---")

    hrefs = []
    print("  Per størrelse (etikett, href, evt. utsolgt-flagg, anker-utdrag):")
    for (s, e, href, label) in grid:
        hrefs.append(href)
        atag = anchor_around(html, s)
        flags = [w for w in SOLD_WORDS if w in atag.lower()]
        print("     [%-5s] %s  %s" % (label, href, ("<<%s>>" % ",".join(flags)) if flags else ""))
        print("            %s" % atag[:260])

    print("  Felles colorway-prefiks: %r" % common_prefix(hrefs))
    rhits = {w: region.lower().count(w) for w in SOLD_WORDS if w in region.lower()}
    print("  Utsolgt-/disabled-ord i grid-region: %s" % (rhits or "INGEN"))
    return hrefs


def main():
    print("probe_brukas v4 — størrelses-grid A/B-avgjørelse")
    all_sibs = {}
    for seed in SEEDS:
        try:
            all_sibs[seed] = probe_one(seed)
        except Exception as e:
            print("  FEIL under %s: %s" % (seed, e))
            all_sibs[seed] = []

    first = next((v for v in all_sibs.values() if v), [])
    print("\n" + "=" * 78)
    print("SØSKEN-SJEKK (per-størrelse JSON-LD: availability + gtin) — beviser om B virker")
    seen = set()
    for href in first:
        if href in seen:
            continue
        seen.add(href)
        if len(seen) > 5:
            break
        st, html = get(href)
        p = ld_product(html) or {}
        off = p.get("offers") or {}
        if isinstance(off, list):
            off = off[0] if off else {}
        print("  %s\n     -> HTTP %s | name=%r\n        gtin=%s avail=%s price=%s"
              % (href, st, p.get("name"), p.get("gtin"),
                 off.get("availability"), off.get("price")))

    print("\nKONKLUSJON-HINT:")
    print("  * Utsolgt-flagg/-klasse synlig i grid-region -> fiks A (les raden fra én side).")
    print("  * Ellers, men søsken-sider gir egen avail+gtin -> fiks B (hent per størrelse).")


if __name__ == "__main__":
    main()
