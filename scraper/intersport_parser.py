"""
intersport_parser.py — parser for Intersport (SportHolding-plattformen, Next.js).

Intersport server-rendrer via Next.js App Router (RSC). Dataene ligger tre steder
i dokumentet, og vi kombinerer dem:
  1) JSON-LD (<script type="application/ld+json"> @type=Product): navn, merke,
     pris, valuta, availability, url.
  2) En skjult Videoly-div `videoly-product-id` (f.eks.
     "asics-1011b958-white-fawn-102_ino_no") gir full colorway-kode (1011B958-102)
     og fargenavn.
  3) Next.js RSC-payloaden har en `variants`-array med per-størrelse `size`,
     `skuId` (=EAN) og `inventory` (antall per lager) — altså EAN OG faktiske antall.

Returnerer en OfferRecord kompatibel med loader.load().
"""

from __future__ import annotations
import re, json

LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
VIDEOLY_ID_RE = re.compile(r'videoly-product-id"[^>]*>\s*asics-([0-9a-z]+)-(.+?)-(\d+)_', re.I)


def _gender_from_url(url: str) -> str:
    u = (url or "").lower()
    if "-dame-" in u or "/dame" in u: return "dame"
    if "-herre-" in u or "/herre" in u: return "herre"
    if "-barn-" in u or "/barn" in u: return "barn"
    return "unisex"


def _extract_variants(html: str) -> list[dict]:
    """Hent RSC `variants`-arrayen (escaped JSON inni en JS-streng)."""
    i = html.find('variants\\":[')
    if i < 0:
        return []
    start = html.find('[', i)
    depth, k = 0, start
    while k < len(html):
        c = html[k]
        if c == '[': depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0: break
        k += 1
    raw = html[start:k + 1].replace('\\\\', '\\').replace('\\"', '"')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def parse_intersport(html: str, url: str = "") -> dict:
    # 1) JSON-LD Product
    product_ld = None
    for blk in LD_RE.findall(html):
        try:
            d = json.loads(blk)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            product_ld = d
            break
    product_ld = product_ld or {}
    offer = product_ld.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}

    brand = (product_ld.get("brand") or {}).get("name") if isinstance(product_ld.get("brand"), dict) else product_ld.get("brand")
    model = product_ld.get("name")
    ld_url = offer.get("url") or url

    # 2) Videoly-div -> colorway-kode + fargenavn
    manufacturer_code, color = None, None
    m = VIDEOLY_ID_RE.search(html)
    if m:
        stem, colorslug, num = m.group(1), m.group(2), m.group(3)
        manufacturer_code = f"{stem.upper()}-{num}"
        color = "/".join(w.capitalize() for w in colorslug.split("-"))

    # 3) RSC-varianter -> per-størrelse EAN + lager
    sizes = []
    for v in _extract_variants(html):
        inv = v.get("inventory")
        qty = sum(w.get("quantity", 0) for w in inv) if isinstance(inv, list) else 0
        sizes.append({
            "size_label": v.get("size"),
            "ean": v.get("skuId"),
            "in_stock": qty > 0,
            "stock_count": qty if isinstance(inv, list) else None,
        })

    return {
        "store": {"slug": "intersport", "name": "Intersport", "source": "scrape", "network": None},
        "brand": brand or "Asics",
        "model": model,
        "gender": _gender_from_url(ld_url),
        "product_line": None,
        "category": "running",
        "color": color,
        "manufacturer_code": manufacturer_code,
        "image_url": product_ld.get("image"),
        "store_sku": manufacturer_code,
        "url": ld_url,
        "currency": offer.get("priceCurrency", "NOK"),
        "price": offer.get("price"),
        "sizes": sizes,
    }


if __name__ == "__main__":
    import sys
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    rec = parse_intersport(html, sys.argv[2] if len(sys.argv) > 2 else "")
    print(json.dumps({k: v for k, v in rec.items() if k != "sizes"}, ensure_ascii=False, indent=1))
    for s in rec["sizes"]:
        print(f"  {s['size_label']:>5}  EAN={s['ean']}  qty={s['stock_count']}  in_stock={s['in_stock']}")
