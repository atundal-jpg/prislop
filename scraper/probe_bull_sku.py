#!/usr/bin/env python3
"""
probe_bull_sku.py — recon av ARTIKKELKODE-felt på Bull-produktsider.

Bakgrunn (27. juli): prislop.offers vokste fra 5 390 (18. juli) til ~11 000
rader, ca. +155 per harvest, og hele veksten var Bull. Årsaken er at
bull_parser bare kjenner kodeformatet til Asics (1011B867-101) og Hoka
(1147911-CSLP). Saucony, adidas og Kiprun ble lagt til i discovery.by_brand i
PR #18 uten at parseren lærte deres format, så store_sku ble NULL for de
merkene. Loaderens variant-matching hadde da ingen nøkkel igjen (Bull har
verken produsentkode eller per-størrelse EAN i markupen) og opprettet ny
variant + nytt tilbud ved HVER kjøring.

Denne proben GJETTER IKKE formatene — den dumper alle feltene koden KAN ligge
i, per merke, så vi kan lese oss fram til riktig regex før vi rører
bull_parser.CODE_RE:

  1. og:image-filnavnet (dagens primærkilde).
  2. JSON-LD: sku / mpn / gtin* / productID / identifier / model på Product-noder.
  3. Etikett-treff i teksten: «Produktnummer», «Art#», «Artikkelnummer»,
     «Varenummer», «Art.nr», «SKU», «Modellnummer», «EAN» — med kontekst.
  4. <meta>-tagger med sku/product/item/id i name/property.
  5. Fritekst-skann etter kode-FORMEDE tokens (bokstav/tall-blokk + bindestrek),
     med antall — avslører formater vi ikke kjenner fra før.
  6. Hva bull_parser.parse() gir i dag (kode/SKU/pris/størrelser) for samme side.

Kjøres via probe.yml (script=probe_bull_sku.py). Kun stdlib — `requests` er
ikke installert i probe-miljøet.
"""
from __future__ import annotations
import json
import re
import sys
import types
import urllib.request
from collections import Counter

# discovery importerer loader (-> psycopg2), som ikke finnes i probe-miljøet.
if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser
import discovery

# Merker vi mangler kode for (Saucony/adidas/Kiprun) + de to som virker
# (Hoka/Asics), som fasit på hvordan et TREFF skal se ut i dumpen.
BRANDS = ["saucony", "adidas", "kiprun", "hoka", "asics"]
PER_BRAND = 2                      # antall produktsider per merke

HEADERS = {
    "User-Agent": "Mozilla/5.0 (prislop)",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5",
}

LD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
META_RE = re.compile(r"<meta\b[^>]*>", re.I)
OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"', re.I)
TAG_RE = re.compile(r"<[^>]+>")

LABELS = ["Produktnummer", "Art#", "Art.nr", "Artikkelnummer", "Varenummer",
          "SKU", "Modellnummer", "Style", "EAN"]

# Bevisst VID: alfanumerisk blokk + skilletegn + alfanumerisk blokk. Vi vil se
# hva som FINNES, ikke bekrefte det vi allerede tror. Filtreres etterpå mot
# åpenbar støy (css-klasser, datoer, url-slugs).
TOKEN_RE = re.compile(r"\b([A-Za-z0-9]{3,12}[-_][A-Za-z0-9]{2,8}(?:[-_][A-Za-z0-9]{1,6})?)\b")
NOISE_RE = re.compile(
    r"^(?:\d{1,2}[-_]\d{1,2}|utf[-_]8|ld\+json|nb[-_]NO|en[-_]US|x[-_]\w+|"
    r"20\d\d[-_]\d\d)$", re.I)


def get(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil {url}: {e}")
        return None


def text_of(html: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html))


def dump_jsonld(html: str) -> None:
    keys = ("sku", "mpn", "gtin", "gtin8", "gtin12", "gtin13", "gtin14",
            "productID", "identifier", "model", "productid")
    found = False
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception as e:
            print(f"      [JSON-LD ugyldig: {e}]")
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        if not isinstance(nodes, list):
            nodes = [nodes]
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get("@type")
            hits = {k: n[k] for k in keys if n.get(k) not in (None, "")}
            offers = n.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                for k in keys:
                    if offers.get(k) not in (None, ""):
                        hits[f"offers.{k}"] = offers[k]
            if hits:
                found = True
                print(f"      @type={t!r} -> {json.dumps(hits, ensure_ascii=False)}")
            elif t == "Product":
                found = True
                print(f"      @type='Product' -> INGEN id-felter. "
                      f"nøkler: {sorted(n.keys())}")
    if not found:
        print("      (ingen JSON-LD-noder med id-felter)")


def dump_labels(html: str) -> None:
    txt = text_of(html)
    any_hit = False
    for lab in LABELS:
        for m in list(re.finditer(re.escape(lab), txt, re.I))[:3]:
            any_hit = True
            s = max(0, m.start() - 30)
            print(f"      «{lab}»: …{txt[s:m.end() + 90].strip()}…")
    if not any_hit:
        print("      (ingen av etikettene funnet i sideteksten)")


def dump_meta(html: str) -> None:
    hit = False
    for tag in META_RE.findall(html):
        if re.search(r'(?:name|property|itemprop)="[^"]*(?:sku|mpn|gtin|product|item|id)[^"]*"',
                     tag, re.I):
            hit = True
            print(f"      {tag.strip()[:200]}")
    if not hit:
        print("      (ingen relevante meta-tagger)")


def dump_tokens(html: str) -> None:
    """Kode-FORMEDE tokens i sideteksten + og:image, hyppigst først."""
    txt = text_of(html)
    im = OG_IMAGE_RE.search(html)
    if im:
        txt += " " + im.group(1).replace("/", " ")
    c = Counter(t for t in TOKEN_RE.findall(txt) if not NOISE_RE.match(t))
    if not c:
        print("      (ingen kode-formede tokens)")
        return
    for tok, n in c.most_common(12):
        flag = " <-- CODE_RE treffer" if bull_parser.CODE_RE.search(tok) else ""
        print(f"      {tok:<24} x{n}{flag}")


def main() -> int:
    print("=" * 78)
    print("PROBE: artikkelkode-felt på Bull-produktsider (ingen antakelser)")
    print("=" * 78)

    for brand in BRANDS:
        print()
        print("#" * 78)
        print(f"# MERKE: {brand}")
        print("#" * 78)
        try:
            urls = discovery.discover(None, "bull", brand, "")
        except Exception as e:
            print(f"  discovery-feil: {e}")
            continue
        print(f"  discovery: {len(urls)} løpesko-URL-er")
        for url in urls[:PER_BRAND]:
            print()
            print(f"  --- {url}")
            html = get(url)
            if not html:
                continue

            im = OG_IMAGE_RE.search(html)
            print(f"    [1] og:image  : {im.group(1) if im else '(mangler)'}")
            print("    [2] JSON-LD id-felter:")
            dump_jsonld(html)
            print("    [3] etiketter i sideteksten:")
            dump_labels(html)
            print("    [4] meta-tagger:")
            dump_meta(html)
            print("    [5] kode-formede tokens:")
            dump_tokens(html)

            rec = bull_parser.parse(html, url)
            if rec is None:
                print("    [6] bull_parser.parse() -> None")
            else:
                print(f"    [6] bull_parser: brand={rec['brand']!r} "
                      f"model={rec['model']!r} pris={rec['price']} "
                      f"kode={rec['manufacturer_code']!r} "
                      f"store_sku={rec['store_sku']!r} "
                      f"str={len(rec['sizes'])}")

    print()
    print("=" * 78)
    print("FERDIG — les [2]/[3]/[5] per merke FØR CODE_RE endres.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
