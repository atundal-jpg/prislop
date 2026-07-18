#!/usr/bin/env python3
"""
probe_bull_vendors.py — vendor-id-recon for Bull Ski & Kajakk (Drupal/ES).

Bakgrunn (18. juli): bruker fant Hoka Skyward X hos Bull som mangler i
katalogen. Årsak i discovery.py: Bull-konfigen er merke-bundet til Asics —
API-URL-en har hardkodet vendor-facet 13524 (Asics), og discover() returnerer
[] for alle andre merker. Kommentaren i discovery.py sier selv «trenger egen
vendor-id-recon per merke» — det er denne proben.

Proben gjør fire ting:
  1. Dumper responsstrukturen fra /api/navigation/product (topp-nøkler,
     ett komplett item, ev. aggregations/facets-blokk) så vi ser hvor
     vendor-id-ene ligger.
  2. Søker ?query=<merke> for hvert av de 10 merkene i brands.BRANDS og
     samler alle vendor-relaterte felter fra items + facets.
  3. For hver kandidat-vendor-id: paginerer product_vendor[0]=<id> og teller
     produkter med «Løpesko» i product_category_text (= hva discovery ville
     funnet).
  4. Henter Skyward X-produktsiden og kjører bull_parser.parse på den —
     CODE_RE i parseren er Asics-spesifikk (4 siffer+bokstav+3 siffer), så
     vi må se hva som skjer med Hoka-koder, pris, størrelser og merke.

Kjøres via probe.yml (script=probe_bull_vendors.py). Kun stdlib.
"""
from __future__ import annotations
import json
import re
import sys
import time
import types
import urllib.request
from urllib.parse import quote_plus

if "psycopg2" not in sys.modules:                     # bull_parser er ren, men
    _pg = types.ModuleType("psycopg2")                # vane fra andre prober
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser
from brands import BRANDS

BASE = "https://bull-ski-kajakk.no"
API = BASE + "/api/navigation/product"
SKYWARD_URL = BASE + "/sko/lopesko/lettvekt-konkurransesko/hoka-skyward-x-herre"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (prislop)",
    "Accept": "application/json, */*",
    "Referer": BASE + "/sko/lopesko",
}


def get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"    API-feil {url}: {e}")
        return None


def get_html(url: str) -> str | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (prislop)",
                          "Accept-Language": "nb-NO"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil {url}: {e}")
        return None


def vendor_fields(obj, path="", out=None):
    """Alle (sti, verdi)-par der nøkkelen inneholder vendor/brand/merke."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if re.search(r"vendor|brand|merke", k, re.I):
                out.append((p, v))
            vendor_fields(v, p, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:40]):
            vendor_fields(v, f"{path}[{i}]", out)
    return out


def main():
    # --- 1) Responsstruktur --------------------------------------------------
    print("=" * 78)
    print("1) STRUKTUR: query=hoka, side 1")
    d = get_json(f"{API}?query=hoka&page=1")
    if d:
        print("  topp-nøkler:", sorted(d.keys()))
        print("  found:", d.get("found"))
        items = d.get("items") or []
        if items:
            print("  --- komplett item[0] ---")
            print(json.dumps(items[0], ensure_ascii=False, indent=1)[:3500])
        for k in ("aggregations", "facets", "filters", "aggs"):
            if k in d:
                print(f"  --- {k} ---")
                print(json.dumps(d[k], ensure_ascii=False, indent=1)[:3500])

    # --- 2) Vendor-felter per merke -----------------------------------------
    print("=" * 78)
    print("2) VENDOR-RECON per merke (query=<merke>)")
    candidates: dict[str, set] = {}
    for brand in BRANDS:
        d = get_json(f"{API}?query={quote_plus(brand.lower())}&page=1")
        if not d:
            continue
        found = d.get("found")
        vf = vendor_fields(d)
        vals = sorted({str(v) for _, v in vf
                       if isinstance(v, (str, int)) and str(v).strip()})
        print(f"  {brand:<12} found={found}  vendor-felter: {vals[:12]}")
        if vf:
            # vis stiene én gang (første merke med treff)
            if not candidates:
                for p, v in vf[:10]:
                    print(f"    sti: {p} = {v!r}")
        candidates[brand] = set(vals)
        time.sleep(0.5)

    # --- 3) Løpesko-telling per kandidat-vendor-id --------------------------
    print("=" * 78)
    print("3) LØPESKO-TELLING per numerisk vendor-id-kandidat")
    ids = sorted({v for s in candidates.values() for v in s
                  if re.fullmatch(r"\d{3,6}", v)})
    print("  kandidat-id-er:", ids, " (13524 = kjent Asics)")
    for vid in ids:
        total = lopesko = 0
        sample = None
        for page in range(1, 11):
            d = get_json(f"{API}?product_vendor%5B0%5D={vid}&query=&page={page}")
            items = (d or {}).get("items") or []
            if not items:
                break
            for it in items:
                total += 1
                if "Løpesko" in (it.get("product_category_text") or []):
                    lopesko += 1
                    if sample is None:
                        sample = it.get("url") or it.get("title")
            if d.get("found") and page * 32 >= d["found"]:
                break
            time.sleep(0.4)
        print(f"  vendor={vid}: totalt={total}, løpesko={lopesko}, eks: {sample}")

    # --- 4) bull_parser på Skyward X-siden ----------------------------------
    print("=" * 78)
    print("4) BULL_PARSER på", SKYWARD_URL)
    html = get_html(SKYWARD_URL)
    if html:
        print("  HTML-lengde:", len(html))
        rec = bull_parser.parse(html, SKYWARD_URL)
        if rec is None:
            print("  parse() -> None!")
        else:
            slim = {k: v for k, v in rec.items() if k != "sizes"}
            print(json.dumps(slim, ensure_ascii=False, indent=1))
            for s in rec["sizes"]:
                print(f"    {s['size_label']:>5}  in_stock={s['in_stock']}")
        # rå produktnummer-kontekst — hva slags kodeformat bruker Hoka hos Bull?
        for m in re.finditer(r"Produktnummer", html):
            snip = re.sub(r"\s+", " ", html[m.start():m.start() + 200])
            print("  Produktnummer-kontekst:", snip)
            break
    print("=" * 78)
    print("Les av: Hokas vendor-id + løpesko-antall -> utvid Bull-konfigen i")
    print("discovery.py; sjekk om CODE_RE i bull_parser.py må lære Hoka-format.")


if __name__ == "__main__":
    main()
