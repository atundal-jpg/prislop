#!/usr/bin/env python3
"""
probe_bull_discovery.py — siste Bull-rekognosering før kode.

Listing-en rendres klient-side via Elasticsearch (ingen produkt-lenker i server-
HTML). Vi trenger derfor en enumererings-vei. Proben sjekker:

  A) robots.txt + XML-sitemap-kandidater -> teller Asics-sko-produkt-URL-er
     (enkleste discovery hvis den finnes).
  B) drupalSettings['elasticsearchUi'] fra /sko/lopesko -> ES-endepunkt/-config
     (fallback-discovery + bekrefter index/host).
  C) PDP-detaljer på én sko -> Produktnummer / Farge / pris / <select>-størrelser
     + utdrag av drupalSettings rundt variation/stock (parser-grunnlag).

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"

SETTINGS_RE = re.compile(
    r'data-drupal-selector="drupal-settings-json"[^>]*>(\{.*?\})</script>', re.S)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.I)
ASICS_SKO = re.compile(r"/sko/[a-z0-9/_-]*asics-", re.I)
SELECT_RE = re.compile(r"<select[^>]*>(.*?)</select>", re.S | re.I)
OPTION_RE = re.compile(r"<option[^>]*>([^<]+)</option>", re.I)


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def section_a() -> None:
    print("== A) robots.txt + sitemap ==")
    cands = []
    try:
        rob = get(BASE + "/robots.txt")
        cands += [l.split(":", 1)[1].strip() for l in rob.splitlines()
                  if l.lower().startswith("sitemap:")]
        print(f"  robots.txt Sitemap-linjer: {cands or '(ingen)'}")
    except Exception as e:
        print(f"  robots.txt FEIL: {e}")
    cands += [BASE + "/sitemap.xml", BASE + "/sitemap_index.xml",
              BASE + "/sitemap/default/sitemap.xml"]
    seen = set()
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        try:
            xml = get(u)
        except Exception as e:
            print(f"  {u} -> FEIL: {e}")
            continue
        locs = LOC_RE.findall(xml)
        subs = [l for l in locs if l.endswith(".xml")]
        shoes = [l for l in locs if "/sko/" in l]
        asics = [l for l in locs if ASICS_SKO.search(l)]
        print(f"  {u}: {len(locs)} <loc>  ({len(subs)} under-sitemaps, "
              f"{len(shoes)} /sko/, {len(asics)} asics-sko)")
        if subs:
            print(f"     under-sitemaps: {subs[:6]}")
        if asics:
            print(f"     asics-sko ex: {asics[:3]}")


def section_b() -> None:
    print("\n== B) elasticsearchUi-config (fra /sko/lopesko) ==")
    try:
        html = get(BASE + "/sko/lopesko")
    except Exception as e:
        print(f"  FEIL: {e}")
        return
    m = SETTINGS_RE.search(html)
    if not m:
        print("  ingen drupalSettings")
        return
    try:
        s = json.loads(m.group(1))
    except Exception as e:
        print(f"  JSON-feil: {e}")
        return
    es = s.get("elasticsearchUi") or s.get("elasticsearch_ui")
    print("  elasticsearchUi:", (json.dumps(es, ensure_ascii=False)[:1400] if es else "(mangler)"))


def section_c() -> None:
    print("\n== C) PDP-parserdetaljer (superblast-3-unisex) ==")
    url = BASE + "/sko/lopesko/treningssko/asics-superblast-3-unisex-1"
    try:
        html = get(url)
    except Exception as e:
        print(f"  FEIL: {e}")
        return
    code = re.search(r"Produktnummer[^0-9]{0,40}?([0-9]{4}[A-Za-z][0-9]{3}-[0-9]{2,3})", html)
    farge = re.search(r"Farge[\s:]{0,8}(?:<[^>]*>\s*){0,3}([A-Za-zÆØÅæøå][A-Za-zÆØÅæøå0-9/ .&-]{2,40})", html)
    price = re.search(r"(\d[\d\s\u00a0]{2,7})\s*,-", html)
    print(f"  Produktnummer: {code.group(1) if code else '?'}")
    print(f"  Farge: {farge.group(1).strip() if farge else '?'}")
    print(f"  pris: {price.group(1).strip() if price else '?'}")
    sel = SELECT_RE.search(html)
    opts = [o.strip() for o in OPTION_RE.findall(sel.group(1))] if sel else []
    print(f"  størrelser ({len(opts)}): {opts[:16]}")
    m = SETTINGS_RE.search(html)
    if m:
        raw = m.group(1)
        for kw in ["variation", "stock", "gtin", "field_size", "attribute_size"]:
            i = raw.lower().find(kw)
            if i >= 0:
                print(f"  drupalSettings ...{kw}: {raw[max(0,i-30):i+130]}")


def main() -> None:
    print("probe_bull_discovery\n")
    section_a()
    section_b()
    section_c()


if __name__ == "__main__":
    main()
