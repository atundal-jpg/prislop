#!/usr/bin/env python3
"""
probe_bull_saucony_sweep.py — hvor mange Bull-URL-er kollapser til samme
variantnøkkel?

Bakgrunn (28. juli, etter probe_bull_discovery_drift): discovery finner 691
Bull-URL-er, men siste last hadde bare 648 distinkte URL-er. Fordelt per merke
(prod-tall mot discovery-tall) ligger nesten hele gapet hos Saucony:

    adidas   43/43     kiprun 17/17    hoka 329/336
    asics   160/162    saucony 99/133  <-- 34 URL-er forsvinner

Discovery er altså ikke problemet — den leverer URL-ene. Tapet skjer i
loaderen: get_or_create_variant nøkler på manufacturer_code FØRST, og
upsert_offer dropper enhver record som treffer samme (butikk, variant) senere
i samme kjøring når prisen er >= den vi alt har. Merk >=: LIKE priser droppes
også. To URL-er med samme kode blir derfor til ÉN tilbudsrad, og den andre
URL-en forsvinner stille fra lasten — uten at noe feiler.

Drift-proben fant én slik kollisjon (S11023-121 delt av triumph-23-dame-3 og
-dame-6). Denne proben måler hele Saucony-katalogen: den henter og parser hver
eneste URL discovery gir for merket, grupperer på manufacturer_code og
rapporterer nøyaktig hvor mange URL-er som kollapser. Faller «distinkte koder»
sammen med de 99 URL-ene prod faktisk har, er årsaken bevist.

Kjøres via probe.yml (script=probe_bull_saucony_sweep.py). Kun stdlib.
"""
from __future__ import annotations
import sys
import types
import urllib.error
import urllib.request
from collections import defaultdict

if "psycopg2" not in sys.modules:                 # loader (via discovery)
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser
import discovery

BRAND = sys.argv[1] if len(sys.argv) > 1 else "saucony"


def get_html(url: str) -> str | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (prislop)",
                      "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil {url}: {e}")
        return None


def main():
    urls = discovery.discover(None, "bull", BRAND, "")
    print("=" * 78)
    print(f"{BRAND.upper()}: discovery ga {len(urls)} URL-er — henter og "
          "parser alle")
    print("=" * 78)

    by_code: dict[str, list[str]] = defaultdict(list)
    legacy_keys: dict[str, list[str]] = {}
    parsed, failed, none_code = 0, 0, []
    for i, url in enumerate(urls, 1):
        html = get_html(url)
        if not html:
            failed += 1
            continue
        try:
            rec = bull_parser.parse(html, url)
        except Exception as e:
            print(f"    parse-feil {url}: {e}")
            failed += 1
            continue
        if rec is None:
            print(f"    parse() -> None: {url}")
            failed += 1
            continue
        parsed += 1
        code = rec.get("manufacturer_code")
        slug = url.rsplit("/", 1)[-1]

        # A/B: hva ville den GAMLE kjeden (med fri-tekst-grenen) gitt på
        # nøyaktig samme markup? Lar oss måle hva bug-en koster i dag, ikke
        # bare hva den kostet 28. juli — Bulls katalog endrer seg under oss.
        legacy = code
        if not legacy:
            rm = bull_parser.RELATED_RE.search(html)
            head = html[:rm.start()] if rm else html
            if cm := bull_parser.CODE_RE.search(head):
                legacy = cm.group(1).upper()
        lkey = (f"{rec.get('model')}|{rec.get('gender')}|{legacy}"
                if legacy else f"URL|{slug}")
        legacy_keys.setdefault(lkey, []).append(slug)

        if code:
            # Variantnøkkelen i loaderen er (produkt, kode). Produktet er
            # (merke, modell, kjønn) — ta det med, ellers ser vi kollisjoner
            # som loaderen ikke ville sett.
            key = f"{rec.get('model')}|{rec.get('gender')}|{code}"
            by_code[key].append(slug)
        else:
            none_code.append(slug)
        if i % 25 == 0:
            print(f"  ... {i}/{len(urls)}")

    collisions = {k: v for k, v in by_code.items() if len(v) > 1}
    lost = sum(len(v) - 1 for v in collisions.values())

    print("\n" + "=" * 78)
    print("RESULTAT")
    print(f"  URL-er fra discovery:            {len(urls)}")
    print(f"  parset OK:                       {parsed}")
    print(f"  fetch/parse-feil:                {failed}")
    print(f"  uten manufacturer_code:          {len(none_code)}")
    print(f"  distinkte (modell, kjønn, kode): {len(by_code)}")
    print(f"  kolliderende nøkler:             {len(collisions)}")
    print(f"  URL-er som TAPES i kollisjoner:  {lost}")
    print(f"  => forventet antall tilbudsrader: {len(by_code) + len(none_code)}")

    if collisions:
        print("\n  KOLLISJONER (samme modell+kjønn+kode på flere URL-er):")
        for key, slugs in sorted(collisions.items()):
            model, gender, code = key.split("|")
            print(f"    {model} {gender} kode={code}: {len(slugs)} URL-er")
            for s in slugs:
                print(f"       {s}")
    if none_code:
        print(f"\n  UTEN KODE ({len(none_code)}) — nøkles på (butikk, SKU) i "
              "loaderen, der SKU er JSON-LD-GTIN-en (distinkt per fargevei); "
              "(butikk, url) er backstoppen under den:")
        for s in none_code[:20]:
            print(f"    {s}")

    legacy_coll = {k: v for k, v in legacy_keys.items() if len(v) > 1}
    legacy_lost = sum(len(v) - 1 for v in legacy_coll.values())
    print("\n" + "=" * 78)
    print("A/B PÅ SAMME MARKUP — hva koster bug-en i dag?")
    print(f"  GAMMEL kjede (med fri-tekst):  {len(legacy_keys)} nøkler, "
          f"{len(legacy_coll)} kollisjoner, {legacy_lost} URL-er tapt")
    print(f"  NY kjede (uten fri-tekst):     "
          f"{len(by_code) + len(none_code)} nøkler, {len(collisions)} "
          f"kollisjoner, {lost} URL-er tapt")
    if legacy_coll:
        print("  Gamle kollisjoner som fiksen fjerner:")
        for k, v in sorted(legacy_coll.items()):
            print(f"    {k}: {len(v)} URL-er -> {v}")

    print("\n" + "=" * 78)
    print("TOLKNING")
    print(f"  Prod har i dag 99 distinkte Saucony-URL-er i siste last.")
    print(f"  Denne proben forventer {len(by_code) + len(none_code)} "
          "tilbudsrader av "
          f"{len(urls)} URL-er.")
    print("  Stemmer de to tallene, er kode-kollisjon i loaderen årsaken —")
    print("  ikke discovery, ikke parseren, ikke butikken.")


if __name__ == "__main__":
    main()
