#!/usr/bin/env python3
"""
probe_loplabbet_pages.py — finn pagineringen på Löplabbets Asics-listing.

/lopesko?Brand=ASICS server-rendrer ~15 produkt-lenker (side 1). Denne proben
prøver de vanligste param-stilene og rapporterer hvor mange UNIKE produkt-lenker
hver gir, og om side 2 skiller seg fra side 1 (= ekte paginering vi kan følge).

Kjøres i GitHub Actions (loplabbet.no er nåbar der). Skriver ingenting til DB.
"""
from __future__ import annotations
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
SLUG_RE = re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}\b", re.I)
HREF_RE = re.compile(r'href="([^"#]+)"', re.I)

BASE = "https://loplabbet.no/lopesko?Brand=ASICS"
CANDIDATES = [
    BASE,                       # side 1 (referanse)
    BASE + "&page=2",
    BASE + "&page=3",
    BASE + "&p=2",
    BASE + "&offset=15",
    BASE + "&skip=15",
    BASE + "&size=200",         # be om stor sidestørrelse
    BASE + "&pageSize=200",
    BASE + "&perPage=200",
]


def links(url: str) -> set[str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    return {h for h in HREF_RE.findall(html) if SLUG_RE.search(h)}


def main() -> None:
    page1 = None
    for url in CANDIDATES:
        try:
            hits = links(url)
        except Exception as e:
            print(f"{url}\n    FEIL: {e}")
            continue
        if page1 is None:
            page1 = hits
            print(f"{url}\n    lenker={len(hits)}  (referanse/side 1)")
            continue
        only_new = hits - page1
        print(f"{url}\n    lenker={len(hits)}  nye-vs-side1={len(only_new)}"
              f"  {'<-- EKTE PAGINERING' if only_new else '(samme som side 1)'}")


if __name__ == "__main__":
    main()
