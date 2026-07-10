#!/usr/bin/env python3
"""
probe_bull_price.py — finn hvor den EKTE prisen ligger i Bulls produkt-HTML.

Bakgrunn (10. juli): bull_parser.py sitt PRICE_RE tar FØRSTE «tall,-»-treff
i HTML-en — som er fraktbanneret «Fri frakt fra 1399,-» øverst på alle sider.
Alle 160 Bull-tilbud sto derfor med pris 1399 uansett faktisk pris (avdekket
av bruker: sko vist til 1399 kostet 1840/2300 hos Bull). Bull er midlertidig
ekskludert fra frontend-visningene (se Migrations-kommentar) til dette er
fikset.

Proben henter 3 kjente, levende Bull-produktsider og skriver ut:
  1. ±240 tegn kontekst rundt HVERT «tall,-»-treff (nummerert, med posisjon)
  2. ±240 tegn rundt kjente fasit-tall (1840, 2300 — brukerobservert
     salgspris/ordinærpris på Kayano 32 Dame) og «pris»-nøkkelord
  3. Alle <script type="application/ld+json">-blokker i sin helhet
Fra utskriften leser vi det ekte prisfeltets format og posisjon, og strammer
parseren deretter.

Kjøres via probe.yml (script=probe_bull_price.py). psycopg2 stubbes.
"""
from __future__ import annotations
import re, sys, types, urllib.request

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
    class Fetcher:
        def get(self, url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (prislop-probe)",
                                                       "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e)); return None

# Levende sider per 10. juli (fra offers-tabellen; den første er skoen
# brukeren faktisk sammenlignet — fasit: ordinær 2300, salg 1840):
URLS = [
    "https://bull-ski-kajakk.no/sko/lopesko/treningssko/asics-gel-kayano-32-dame-2",
    "https://bull-ski-kajakk.no/sko/lopesko/treningssko/asics-gel-kayano-32-dame-3",
    "https://bull-ski-kajakk.no/sko/lopesko/treningssko/asics-gel-kayano-31-herre-0",  # utgått — kontrast
]

KOMMA_STREK = re.compile(r"\d[\d\s\u00a0]{2,7},-")
FASIT = re.compile(r"(1\s?840|2\s?300|[Pp]ris|price)")
LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def ctx(html: str, start: int, end: int, pad: int = 240) -> str:
    s = html[max(0, start - pad): end + pad]
    return re.sub(r"\s+", " ", s).strip()


def main():
    f = Fetcher()
    for url in URLS:
        print("=" * 78)
        print("URL:", url)
        html = f.get(url)
        if not html:
            continue
        print("HTML-lengde:", len(html))

        print("\n--- 1) Alle «tall,-»-treff (dagens PRICE_RE tar det FØRSTE) ---")
        for i, m in enumerate(KOMMA_STREK.finditer(html)):
            print(f"[{i}] pos={m.start()}  «{m.group(0)}»")
            print("    ", ctx(html, m.start(), m.end()))
            if i >= 11:
                print("    … (flere treff kuttet)"); break

        print("\n--- 2) Fasit-tall (1840/2300) og pris-nøkkelord ---")
        seen = set()
        for m in FASIT.finditer(html):
            key = m.start() // 300          # grovdedup av nærliggende treff
            if key in seen:
                continue
            seen.add(key)
            print(f"pos={m.start()}  «{m.group(0)}»")
            print("    ", ctx(html, m.start(), m.end()))
            if len(seen) >= 14:
                print("    … (flere kuttet)"); break

        print("\n--- 3) JSON-LD-blokker ---")
        for i, m in enumerate(LD.finditer(html)):
            body = re.sub(r"\s+", " ", m.group(1)).strip()
            print(f"[LD {i}] {body[:900]}")
    print("=" * 78)
    print("Les av: hvilken posisjon/hvilket format har den EKTE salgsprisen,")
    print("finnes ordinærpris/medlemspris i samme område, og har siden JSON-LD")
    print("med offers.price? Fiks strammes deretter i bull_parser.py.")


if __name__ == "__main__":
    main()
