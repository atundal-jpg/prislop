#!/usr/bin/env python3
"""
probe_olympia_bridge.py — sammenligner Olympias produsentkode (MPN, "Produsentens
varenummer") DIREKTE mot Intersport/Sport 1 sin manufacturer_code for samme
fysiske Adidas-/Saucony-fargevei.

Bakgrunn: probe_olympia_ajax fant at Olympia-PDP-er har et itemprop="mpn"-felt
("Produsentens varenummer") som formatmessig er identisk med Adidas/Saucony sin
egen artikkelkode ([a-z]{2}\\d{4,5} for Adidas, s?\\d{5}(-\\d{1,3})? for Saucony)
— nøyaktig den koden Intersport/Sport 1 sin URL-slug (og dermed
sportholding_parser.manufacturer_code, se discovery.py) allerede bygger på.
Samme FORMAT er ikke bevis på samme KODE for samme sko — denne proben sjekker det.

Metode (billig — koden ligger i URL-slugen hos Intersport/Sport1, ingen ekstra
PDP-fetch nødvendig der):
  1) discovery.discover() henter HELE Adidas- og Saucony-katalogen fra
     Intersport og Sport 1 (samme kode discovery/run_pipeline bruker i drift).
  2) Trekk artikkelkoden ut av hver URL-slug -> kode-sett per (butikk, merke).
  3) Hent en håndfull Olympia-PDP-er per merke, les MPN fra
     itemprop="mpn"-meta-taggen.
  4) Sjekk om Olympias MPN finnes i Intersport/Sport1 sitt kode-sett. Et
     TREFF der modellnavnet også åpenbart er samme sko -> broen virker.

GO = minst ett eksakt kode-treff med sammenfallende modellnavn -> Olympia kan
integreres via manufacturer_code, ingen EAN nødvendig.
NO-GO = ingen treff -> butikkene nummererer ulikt trass i identisk format.

Stdlib only + prosjektets egne moduler (discovery/sportholding_parser).
psycopg2 stubbes (loader-importen i discovery.py trenger den, men vi kaller
den aldri). probe.yml (script=probe_olympia_bridge.py).
"""
from __future__ import annotations
import re
import sys
import types
import urllib.request

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
    class Fetcher:
        def __init__(self, *a, **k):
            pass

        def get(self, url):
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (prislop-probe)", "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e))
                return None

import discovery  # noqa: E402  (etter psycopg2-stub)

OLYMPIA_BASE = "https://www.olympiasport.no"
OLYMPIA_CATS = ["/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame"]

TILE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"\s+title="([^"]*)"', re.I)
TILE_LOOSE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"\s+title="([^"]*)"', re.I | re.S)
MPN_RE = re.compile(r'itemprop="mpn"\s+content="([^"]+)"', re.I)

# Kodeformater bekreftet i discovery.py sine marker_re for Intersport/Sport1.
CODE_RE = {
    "adidas": re.compile(r'-([a-z]{2}\d{4,5})(?:/|\?|$)', re.I),
    "saucony": re.compile(r'-(s?\d{5}(?:-\d{1,3})?)(?:/|\?|$)', re.I),
}


def olympia_get(path):
    url = path if path.startswith("http") else OLYMPIA_BASE + path
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (prislop-probe)", "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  olympia fetch-feil %s: %s" % (url, e))
        return ""


def olympia_tiles(brand_slug, n=8):
    found = []
    for cat in OLYMPIA_CATS:
        html = olympia_get(cat)
        t = TILE.findall(html) or TILE_LOOSE.findall(html)
        for h, ti in t:
            if h.lower().startswith(f"/{brand_slug}-") and (h, ti) not in found:
                found.append((h, ti))
        if len(found) >= n:
            break
    return found[:n]


def olympia_mpn(path):
    html = olympia_get(path)
    m = MPN_RE.search(html)
    return m.group(1) if m else None


def store_codes(fetcher, store_slug, brand):
    """Hele merkekatalogens URL-er fra discovery (samme kode som drift bruker),
    med artikkelkoden trukket ut av slugen -> {kode_lower: [URL, ...]}."""
    try:
        urls = discovery.discover(fetcher, store_slug, brand, "", limit=1000)
    except Exception as e:
        print(f"  discovery-feil ({store_slug}/{brand}): {e}")
        return {}
    code_re = CODE_RE[brand]
    out: dict[str, list[str]] = {}
    for u in urls:
        m = code_re.search(u)
        if m:
            out.setdefault(m.group(1).lower(), []).append(u)
    return out


def main():
    print("probe_olympia_bridge — Olympia MPN vs Intersport/Sport1 manufacturer_code\n")
    fetcher = Fetcher()

    print("Henter Olympia-PDP-er (MPN)...")
    olympia_data: dict[str, list[tuple]] = {}
    for brand in ("adidas", "saucony"):
        oly = olympia_tiles(brand, n=8)
        entries = [(href, title, olympia_mpn(href)) for href, title in oly]
        olympia_data[brand] = entries
        print(f"  {brand}: {len(entries)} PDP-er, {sum(1 for _, _, m in entries if m)} med MPN")

    for store_slug, store_name in [("intersport", "Intersport"), ("sport1", "Sport 1")]:
        print("\n" + "=" * 74)
        print("BUTIKK:", store_name)
        for brand in ("adidas", "saucony"):
            print("-" * 74)
            print("MERKE:", brand.upper())
            codes = store_codes(fetcher, store_slug, brand)
            n_urls = sum(len(v) for v in codes.values())
            print(f"  {store_name}: {len(codes)} unike koder funnet ({n_urls} produkt-URL-er)")
            hits = 0
            for href, title, mpn in olympia_data[brand]:
                if not mpn:
                    print(f"    {href} : Olympia MPN mangler")
                    continue
                match_urls = codes.get(mpn.lower())
                if match_urls:
                    hits += 1
                    print(f"    TREFF  Olympia MPN={mpn!r} ({title})")
                    print(f"           == {store_name}: {match_urls[0]}")
                else:
                    print(f"    ingen  MPN={mpn!r} ({title}) finnes IKKE i {store_name} sitt kode-sett")
            print(f"  -> {hits}/{len(olympia_data[brand])} Olympia-PDP-er matchet {store_name}")

    print("\n" + "=" * 74)
    print("KONKLUSJON: se TREFF-linjene over — sjekk manuelt at modellnavnet på")
    print("hver side av == åpenbart er samme sko. Er det det: manufacturer_code-")
    print("broen virker for Olympia (GO, uavhengig av EAN). Ingen treff i det")
    print("hele tatt: butikkene nummererer ulikt trass i identisk format (NO-GO).")


if __name__ == "__main__":
    main()
