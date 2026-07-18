#!/usr/bin/env python3
"""
probe_sportholding_sizefields.py — finnes et EU-størrelsesfelt i RSC-payloaden?

BAKGRUNN (17. juli): sportholding_parser leser variantens `size`-felt rått, og
for Hoka/Saucony hos Löplabbet/Sport 1 er det feltet UK-skala. Resultat: 85
Hoka-chips (+ Saucony unisex m.fl.) vises som «UK X» fordi verken EAN-broen
eller size_chart dekker dem ennå (radene HAR EAN, men ingen annen butikk fører
samme fargevariant med EU-label). Migrasjon 0024 tok de EAN-beviste stigene;
dette er rotårsakssporet.

SPØRSMÅLET proben svarer på: har variantobjektene (eller nabolaget deres i
RSC-payloaden) et felt med EU-størrelsen — f.eks. `sizeEu`, `euSize`,
`sizeSystem`, en attributes-liste e.l. — slik at parseren kan emittere EU
direkte i stedet for UK? I så fall dør hele problemklassen ved ingest, uten
flere size_chart-rader.

DUMPER per side: (a) settet av nøkler i variantobjektene, (b) de to første
variantobjektene i sin helhet (rå JSON), (c) alle forekomster av 'size'-aktige
nøkler i payloaden rundt variants-blokken, med 80 tegn kontekst.

Stdlib only (probe.yml-miljøet har ikke requests).
Kjøres via .github/workflows/probe.yml (script=probe_sportholding_sizefields.py).
"""
from __future__ import annotations
import json
import re
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"

# Berørte sider (fra prod-DB 17. juli): Hoka herre/dame + Saucony unisex hos
# Löplabbet, Hoka herre/unisex hos Sport 1 — alle med UK-labels i offer_sizes.
URLS = [
    "https://loplabbet.no/hoka-mach-5-ceramic-evening-primrose-herre-1127893",
    "https://loplabbet.no/hoka-mach-5-ceramic-evening-primrose-dame-1127894",
    "https://loplabbet.no/saucony-sinister-citronblack-unisex-s29097-05",
    "https://www.sport1.no/hoka-m-bondi-9-varsity-navy-white-herre-1162011",
    "https://www.sport1.no/hoka-u-cielo-x1-30-frost-black-unisex-1171927",
]

SIZEISH_KEY = re.compile(r'\\"(\w*[Ss]ize\w*|\w*[Ee][Uu]\w*)\\":', )


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  FEIL ved henting: {e}")
        return None


def extract_variants_raw(html: str) -> str | None:
    """Samme teknikk som sportholding_parser._extract_variants, men rå tekst."""
    i = html.find('variants\\":[')
    if i < 0:
        return None
    start = html.find('[', i)
    depth, k = 0, start
    while k < len(html):
        c = html[k]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                break
        k += 1
    return html[start:k + 1].replace('\\\\', '\\').replace('\\"', '"')


def main() -> int:
    for url in URLS:
        print(f"\n{'=' * 78}\n{url}")
        html = fetch(url)
        if not html:
            continue

        raw = extract_variants_raw(html)
        if raw is None:
            print("  Ingen 'variants'-blokk funnet i payloaden.")
        else:
            try:
                variants = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"  variants-blokk funnet men JSON feilet ({e}) — første 500 tegn rått:")
                print("  " + raw[:500])
                variants = []
            if variants:
                keys = sorted({k for v in variants if isinstance(v, dict) for k in v})
                print(f"  {len(variants)} varianter. Nøkler: {keys}")
                for v in variants[:2]:
                    print("  variant: " + json.dumps(v, ensure_ascii=False))

        # size-/EU-aktige nøkler i hele payloaden, med kontekst — fanger felt
        # som ligger UTENFOR selve variantobjektene (f.eks. sizeSystem på
        # produktnivå, eller en parallell EU-liste).
        hits = {}
        for m in SIZEISH_KEY.finditer(html):
            key = m.group(1)
            if key in hits:
                continue
            ctx = html[m.start():m.start() + 80].replace("\\", "")
            hits[key] = ctx
        print(f"  size-/EU-aktige nøkler i payloaden ({len(hits)}):")
        for key, ctx in sorted(hits.items()):
            print(f"    {key:<24} | {ctx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
