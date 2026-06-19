"""
sportholding_parser.py — felles parser for SportHolding-plattformen (Next.js).

Samme storefront driver Intersport, Sport 1 og Löplabbet: samme Sanity-org
(gsabfq9z), samme media.sportholding.no, samme produkt-slug som ender på Asics-
stilkoden. Produktsidene legger dataene tre steder, og vi kombinerer dem:
  1) JSON-LD (<script type="application/ld+json"> @type=Product): navn, merke,
     pris, valuta, availability, url.
  2) En skjult Videoly-div `videoly-product-id` (f.eks.
     "asics-1011b958-white-fawn-102_ino_no") -> full colorway-kode (1011B958-102)
     + fargenavn. Intersport og Sport 1 har denne. Löplabbet har den IKKE.
  3) Next.js RSC-payloaden har en `variants`-array med per-størrelse `size`,
     `skuId` (=EAN) og `inventory` (antall per lager) -> EAN OG faktiske antall.

Videoly-løse sider (Löplabbet): vi henter fargenavn fra slug-en og lar
manufacturer_code være None. Da nøkler loaderen fargevarianten på EAN-overlapp
(samme vei som XXL), så colorways verken kolliderer i butikken eller
dubletteres på tvers. Slug-BASIS-koden (uten farge-suffiks, f.eks. 1011C127) er
delt mellom alle farger av en modell og brukes derfor bevisst IKKE som kode.

parse(html, url, store_slug, store_name) -> OfferRecord (loader.load-kompatibel).
parse_intersport(...) beholdes som tynt alias for bakoverkompatibilitet.
"""

from __future__ import annotations
import re, json

LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)

# Asics-spesifikk i dag (vi er Asics-only). Generaliser merke-prefikset her ved
# flermerke-steget i veikartet. Grupper: (stamme/stilkode, fargeslug, fargenr).
VIDEOLY_ID_RE = re.compile(r'videoly-product-id"[^>]*>\s*asics-([0-9a-z]+)-(.+?)-(\d+)_', re.I)

# Trailing Asics-stilkode i slug (4 siffer + bokstav + 3 siffer), f.eks. -1011c127.
SLUG_CODE_RE = re.compile(r"-(\d{4}[a-z]\d{3})(?:/|\?|$)", re.I)

# Ord som ikke er farge når vi utleder farge fra slug.
_DROP_TOKENS = {
    "asics", "herre", "dame", "unisex", "barn", "junior",
    "lopesko", "løpesko", "sko", "joggesko", "terreng",
}

# Noen (ofte eldre) produkter har kategori-ordene med i JSON-LD-navnet, f.eks.
# "GT-2000 12 løpesko herre". Strip dem så modellnavnet blir rent ("GT-2000 12").
_MODEL_SUFFIX_RE = re.compile(
    r"^(?P<model>.*?)\s+(?:terreng)?(?:løpesko|joggesko|sko)"
    r"(?:\s+(?:herre|dame|unisex|barn|junior))?\s*$",
    re.I,
)


def _clean_model(name: str | None) -> str | None:
    if not name:
        return name
    m = _MODEL_SUFFIX_RE.match(name)
    return m.group("model").strip() if m else name.strip()


def _gender_from_url(url: str) -> str:
    u = (url or "").lower()
    if "-dame-" in u or "/dame" in u: return "dame"
    if "-herre-" in u or "/herre" in u: return "herre"
    if "-barn-" in u or "/barn" in u: return "barn"
    return "unisex"


def _color_from_slug(url: str, model: str | None) -> str | None:
    """Utled fargenavn fra produkt-slug når Videoly mangler (Löplabbet).
    Kun til visning (offers.store_color) — INNGÅR IKKE i variant-identiteten."""
    seg = (url or "").rstrip("/").rsplit("/", 1)[-1].split("?")[0].lower()
    seg = SLUG_CODE_RE.sub("", seg)               # fjern trailing stilkode
    drop = set(_DROP_TOKENS)
    for t in re.split(r"[\s\-/]+", (model or "").lower()):
        if t:
            drop.add(t)
    color_parts = [p for p in seg.split("-") if p and p not in drop and not p.isdigit()]
    return "/".join(w.capitalize() for w in color_parts) if color_parts else None


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


def parse(html: str, url: str = "", store_slug: str = "intersport",
          store_name: str = "Intersport") -> dict:
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
    model = _clean_model(product_ld.get("name"))
    ld_url = offer.get("url") or url

    # 2) Videoly-div -> full colorway-kode + fargenavn (Intersport/Sport 1).
    #    Mangler den (Löplabbet): kode=None (EAN-vei i loaderen), farge fra slug.
    manufacturer_code, color = None, None
    m = VIDEOLY_ID_RE.search(html)
    if m:
        stem, colorslug, num = m.group(1), m.group(2), m.group(3)
        manufacturer_code = f"{stem.upper()}-{num}"
        color = "/".join(w.capitalize() for w in colorslug.split("-"))
    else:
        color = _color_from_slug(ld_url or url, model)

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
        "store": {"slug": store_slug, "name": store_name, "source": "scrape", "network": None},
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


def parse_intersport(html: str, url: str = "") -> dict:
    """Bakoverkompatibelt alias."""
    return parse(html, url, "intersport", "Intersport")


if __name__ == "__main__":
    import sys
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    slug = sys.argv[3] if len(sys.argv) > 3 else "intersport"
    rec = parse(html, sys.argv[2] if len(sys.argv) > 2 else "", slug, slug.title())
    print(json.dumps({k: v for k, v in rec.items() if k != "sizes"}, ensure_ascii=False, indent=1))
    for s in rec["sizes"]:
        print(f"  {s['size_label']:>5}  EAN={s['ean']}  qty={s['stock_count']}  in_stock={s['in_stock']}")
