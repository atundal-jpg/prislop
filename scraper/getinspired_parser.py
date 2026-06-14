"""
getinspired_parser.py — parser for GetInspired sine produktsider.

GetInspired (SportHolding-plattformen) server-rendrer alt vi trenger som
Open Graph-meta-tags i HTML-hodet — ingen JS nødvendig:
    product:price:amount, product:price:currency, product:availability,
    product:retailer_item_id (Asics-artikkelkode), product:sizes,
    product:sizes_in_stock
Merk: GetInspired eksponerer IKKE EAN. Kryssnøkkelen her er produsentkoden
(Asics-koden), som broer mot butikker som bare har EAN.

Samme meta-mønster brukes trolig av Anton Sport (samme plattform), så denne
parseren er sannsynligvis gjenbrukbar der med minimal justering.

Returnerer en OfferRecord kompatibel med loader.load().
"""

from __future__ import annotations
import re

META_RE = re.compile(r"<meta\b[^>]*>", re.I)
ASICS_CODE_RE = re.compile(r"(\d{4}[A-Z]\d{3}-\d{3})")


def _meta_map(html: str) -> dict:
    """Plukker ut alle <meta property/name="..."> -> content."""
    out = {}
    for tag in META_RE.findall(html):
        key = re.search(r'(?:property|name)\s*=\s*"([^"]+)"', tag, re.I)
        val = re.search(r'content\s*=\s*"([^"]*)"', tag, re.I)
        if key and val is not None:
            out[key.group(1).lower()] = val.group(1)
    return out


def _gender_from_url(url: str) -> str:
    u = (url or "").lower()
    if "/dame" in u:
        return "dame"
    if "/herre" in u:
        return "herre"
    if "/barn" in u:
        return "barn"
    return "unisex"


def parse_getinspired(html: str, url: str) -> dict:
    m = _meta_map(html)

    # Tittel: "Asics Gel-Nimbus 27 - Blå" -> merke / modell / farge
    title = m.get("og:title", "")
    name_part, _, color = title.partition(" - ")
    name_part = name_part.strip()
    brand, _, model = name_part.partition(" ")     # "Asics" | "Gel-Nimbus 27"
    model = model.strip()
    product_line = re.sub(r"\s*\d+\s*$", "", model).strip().lower().replace(" ", "-") or None

    # Produsentkode (Asics) fra retailer_item_id "c-AS-1011B958-500"
    rid = m.get("product:retailer_item_id", "")
    code_match = ASICS_CODE_RE.search(rid)
    manufacturer_code = code_match.group(1) if code_match else None

    # Størrelser + lagerstatus
    sizes = [s for s in m.get("product:sizes", "").split("|") if s]
    in_stock_set = {s for s in m.get("product:sizes_in_stock", "").split("|") if s}

    price = None
    if m.get("product:price:amount"):
        try:
            price = float(m["product:price:amount"])
        except ValueError:
            price = None

    return {
        "store": {"slug": "getinspired", "name": "Get Inspired", "source": "scrape", "network": None},
        "brand": brand or None,
        "model": model or None,
        "gender": _gender_from_url(url),
        "product_line": product_line,
        "category": "running",
        "color": color.strip() or None,
        "manufacturer_code": manufacturer_code,
        "image_url": m.get("og:image"),
        "store_sku": rid or None,
        "url": m.get("og:url") or url,
        "currency": m.get("product:price:currency", "NOK"),
        "price": price,
        "sizes": [
            {"size_label": s, "ean": None,
             "in_stock": s in in_stock_set, "stock_count": None}
            for s in sizes
        ],
    }


if __name__ == "__main__":
    import sys, json
    html = open(sys.argv[1], encoding="utf-8").read()
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    print(json.dumps(parse_getinspired(html, url), ensure_ascii=False, indent=2))
