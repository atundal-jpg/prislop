#!/usr/bin/env python3
"""
probe_olympia_count.py — teller Olympias distinkte produkter (Adidas + Saucony,
de eneste to av de ti katalogmerkene Olympia fører, jf. probe_olympia v6) på
SAMME match_key-nøkkel katalogen bruker (normalize.product_key), som grunnlag
for å svare: hvor mange nye produkter gir Olympia, og hvor mange matcher noe
som allerede finnes?

Modellnavn hentes fra <h1> på hver PDP — probe_olympia_titles fant at h1 er
tittelen UTEN fargehalen («Adidas Supernova Rise 3», «Saucony Guide 19
Womens»), i motsetning til tile-titlene fra kategori-listingene som har farge
klistret rett på. Kjønn: leses fra et evt. trailing Womens/Mens/Unisex-ord i
h1 (Olympia bruker engelske kjønnsord, ikke normalize.py sine norske Dame/
Herre/Unisex/Barn-mønstre) — mangler det, faller vi tilbake på hvilken
kategori (joggesko-herre/joggesko-dame) tile-en ble funnet i. asfaltsko/
terrengsko er kjønnsblandede kategorier uten en slik fallback — havner
produktet der uten et Womens/Mens-ord i h1, går det til "unisex" som en grov
antagelse (svakhet, ikke en påstand om fasit).

Denne proben beregner KUN Olympias egen distinkte match_key-mengde (ett per
(merke, modell, kjønn) — flere fargeveier av samme modell teller som ETT
produkt, akkurat som i katalogen). Selve sammenligningen mot eksisterende
katalog gjøres utenfor proben (direkte SQL mot prislop.products), siden
denne kjøringen ikke har databasetilgang.

Stdlib only + normalize.py (leaf-modul, ingen psycopg2-avhengighet).
probe.yml (script=probe_olympia_count.py).
"""
from __future__ import annotations
import re
import urllib.request

import normalize

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
CATS = ["/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame"]
CAT_GENDER = {"/joggesko-herre": "herre", "/joggesko-dame": "dame"}

TILE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"\s+title="([^"]*)"', re.I)
TILE_LOOSE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"\s+title="([^"]*)"', re.I | re.S)
PAGER = re.compile(r'[?&]pagenumber=(\d+)', re.I)
H1_RE = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.I | re.S)
BRANDS = {"adidas": "Adidas", "saucony": "Saucony"}


def get(path):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  fetch-feil %s: %s" % (path, e))
        return ""


def tiles(html):
    t = TILE.findall(html) or TILE_LOOSE.findall(html)
    out = []
    for h, ti in t:
        if (h, ti) not in out:
            out.append((h, ti))
    return out


def collect_brand_tiles(brand_slug):
    """[(href, title, source_cat), ...] for gitt merke, på tvers av alle kategorier."""
    found = []
    seen = set()
    for cat in CATS:
        html = get(cat)
        last = min(max([int(x) for x in PAGER.findall(html)] or [1]), 4)
        pages = [(cat, html)] + [(cat, get(f"{cat}?pagenumber={p}")) for p in range(2, last + 1)]
        for src_cat, pg in pages:
            for h, ti in tiles(pg or ""):
                if h.lower().startswith(f"/{brand_slug}-") and h not in seen:
                    seen.add(h)
                    found.append((h, ti, src_cat))
    return found


def strip_trailing_gender(text):
    m = re.search(r'\b(Womens|Mens|Unisex)\b\s*$', text.strip(), re.I)
    if not m:
        return text.strip(), None
    gw = m.group(1).lower()
    gender = {"womens": "dame", "mens": "herre", "unisex": "unisex"}[gw]
    return text[:m.start()].strip(), gender


def clean_model_from_pdp(href, brand_disp):
    html = get(href)
    m = H1_RE.search(html)
    if not m:
        return None, None
    h1 = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    # h1 starter med merkenavnet ("Adidas Supernova Rise 3") -> fjern det,
    # normalize.norm_model ville strippet det uansett, men vi trenger det
    # rene modell-fragmentet for den lokale kjønns-sjekken under.
    if h1.lower().startswith(brand_disp.lower()):
        h1 = h1[len(brand_disp):].strip()
    model, gender = strip_trailing_gender(h1)
    return model, gender


def main():
    print("probe_olympia_count — distinkte produkter (match_key) for Adidas + Saucony\n")
    for slug, disp in BRANDS.items():
        print("=" * 74)
        print("MERKE:", disp)
        tiles_found = collect_brand_tiles(slug)
        print(f"  {len(tiles_found)} fargevei-PDP-er funnet i kategoriene")
        by_key: dict[str, list[str]] = {}
        for href, title, src_cat in tiles_found:
            model, gender = clean_model_from_pdp(href, disp)
            if model is None:
                print(f"    h1 mangler: {href}")
                continue
            gender = gender or CAT_GENDER.get(src_cat) or "unisex"
            bk, mk, gk = normalize.product_key(disp, model, gender)
            match_key = f"{bk}|{mk}|{gk}"
            by_key.setdefault(match_key, []).append(f"{href} ({title})")
        print(f"  -> {len(by_key)} DISTINKTE match_key-er (produkter) blant {len(tiles_found)} fargevei-PDP-er")
        print("\n  MATCH_KEY-LISTE:")
        for mk in sorted(by_key):
            print(f"    {mk}  [{len(by_key[mk])} fargevei(er)]")
            for ex in by_key[mk][:2]:
                print(f"        {ex}")


if __name__ == "__main__":
    main()
