#!/usr/bin/env python3
"""
probe_sportholding_listing.py — hvordan henter vi HELE Asics-katalogen fra
SportHolding-plattformen (Intersport / Sport 1 / Löplabbet)?

Søk-per-modell fanger bare modellene i MODELS-lista (× fargetak × søke-rekkevidde),
så vi mister alt annet butikken fører. XXL/Torshov henter full katalog via butikkens
egne listing-API (eSales/Jetshop). Denne proben leter etter SportHoldings tilsvar,
slik at ÉN løsning løfter alle tre søsken-butikkene til full katalog.

Per butikks listeside:
  1) "NN produkter"-tall + hvor mange produkt-lenker som server-rendres.
  2) Backend-fingeravtrykk: URL-er/script-hosts i HTML som ser ut som søke-/katalog-
     API (apptus/esales/elevate/algolia/klevu/loop54/nosto/graphql//api/), pluss
     config-tokens (customerKey/appId/apiKey/buildId/indexName).
  3) Pagineringstest: prøver ?page=2 / ?p=2 / ?size=200 og ser om NYE produkt-lenker
     dukker opp (= server-side paginering vi kan følge i en take-all).

Tolkning:
  - Backend-API dukker opp  -> skriv én full-katalog-adapter (gjenbrukt av alle tre),
                               à la XXLs eSales / Torshovs Jetshop.
  - Paginering gir nye lenker-> take-all som går side for side.
  - Verken/eller            -> listing lastes klient-side; da trengs ÉN Network-fangst
                               fra desktop (XHR-kallet bak "Filtrer og sorter").

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
SLUG_RE = re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}\b", re.I)
HREF_RE = re.compile(r'href="([^"#]+)"', re.I)
SRC_RE = re.compile(r'src="(https?://[^"]+)"', re.I)
COUNT_RE = re.compile(r"(\d+)\s*produkter", re.I)
BACKEND_RE = re.compile(
    r'https?://[^"\'\s\\]*(?:apptus|esales|elevate|algolia|klevu|loop54|nosto|'
    r'searchspring|findify|graphql|/api/)[^"\'\s\\]*', re.I)
TOKEN_RE = re.compile(
    r'\\?"(customerKey|appId|applicationId|apiKey|engineKey|clusterId|buildId|indexName)'
    r'\\?"\s*:\s*\\?"([^"\\]{1,60})', re.I)

LISTINGS = {
    "intersport": "https://www.intersport.no/asics?Gender=Herre",
    "sport1":     "https://www.sport1.no/asics",
    "loplabbet":  "https://loplabbet.no/lopesko?Brand=ASICS",
}
PAGE_TESTS = {
    "intersport": [
        "https://www.intersport.no/asics?Gender=Herre&page=2",
        "https://www.intersport.no/asics?Gender=Herre&p=2",
        "https://www.intersport.no/asics?Gender=Herre&size=200",
    ],
    "sport1": [
        "https://www.sport1.no/asics?page=2",
        "https://www.sport1.no/asics?p=2",
        "https://www.sport1.no/asics?size=200",
        "https://www.sport1.no/asics?pageSize=200",
    ],
    "loplabbet": [
        "https://loplabbet.no/lopesko?Brand=ASICS&page=2",
        "https://loplabbet.no/lopesko?Brand=ASICS&p=2",
        "https://loplabbet.no/lopesko?Brand=ASICS&size=200",
    ],
}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def links(html: str) -> set[str]:
    return {h for h in HREF_RE.findall(html) if SLUG_RE.search(h)}


def host(u: str) -> str:
    return re.sub(r"^(https?://[^/]+).*", r"\1", u)


def main() -> None:
    for slug, base in LISTINGS.items():
        print(f"\n===== {slug} =====")
        try:
            html = get(base)
        except Exception as e:
            print(f"  FEIL: {e}")
            continue
        cnt = COUNT_RE.search(html)
        page1 = links(html)
        print(f"  {base}")
        print(f"    'NN produkter' = {cnt.group(1) if cnt else '?'}    server-rendret lenker = {len(page1)}")

        backends = sorted(set(BACKEND_RE.findall(html)))[:12]
        ext_hosts = sorted({host(s) for s in SRC_RE.findall(html)})[:15]
        toks = sorted({f"{k}={v}" for k, v in TOKEN_RE.findall(html)})[:12]
        print(f"    backend-API-kandidater: {backends or '(ingen i HTML)'}")
        print(f"    eksterne script-hosts:  {ext_hosts}")
        print(f"    config-tokens:          {toks or '(ingen)'}")

        print("    paginering:")
        for u in PAGE_TESTS.get(slug, []):
            try:
                new = links(get(u))
            except Exception as e:
                print(f"      {u}\n        FEIL: {e}")
                continue
            extra = new - page1
            flag = "<-- NYE LENKER (paginering virker)" if extra else "(samme som side 1)"
            print(f"      {u}\n        lenker={len(new)}  nye={len(extra)}  {flag}")


if __name__ == "__main__":
    main()
