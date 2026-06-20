"""
brukas_parser.py — parser Brukås Sport (nopCommerce).

Særtrekk: hvert produkt er ÉN (farge + størrelse) med egen JSON-LD + EAN. Vi
parser hver side til en «størrelses-partial», og `aggregate()` grupperer dem på
(merke, modell, kjønn, farge) → én OfferRecord per colorway med størrelses-liste.
Brukås har ikke Asics-colorway-kode → matcher på EAN, som XXL/Löplabbet.

Flyt:
  discovery (nopcommerce_pages) → URL-er per størrelse
  _brukas(html,url) → parse_size → [partial]   (i discovery.py)
  harvest_store: aggregate(partials) → [OfferRecord]   (via STORES["brukas"]["aggregate"])
"""
from __future__ import annotations
import json
import re

LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S | re.I)
# "<Modell> <Kjønn> <Størrelse> <Farge>", merke alt strippet
NAME_RE = re.compile(
    r"^(?P<model>.+?)\s+(?P<gender>Herre|Dame|Unisex|Barn|Junior)\s+"
    r"(?P<size>\d{2}(?:[.,]\d)?)\s+(?P<color>.+)$", re.I)
# fallback uten kjønn
NAME_NOGENDER = re.compile(r"^(?P<model>.+?)\s+(?P<size>\d{2}(?:[.,]\d)?)\s+(?P<color>.+)$")
_GENDER = {"herre": "herre", "dame": "dame", "unisex": "unisex",
           "barn": "barn", "junior": "barn"}


def _product_ld(html: str) -> dict | None:
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except json.JSONDecodeError:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") == "Product":
                return it
    return None


def parse_size(html: str, url: str = "") -> dict | None:
    """Én produktside (én farge+størrelse) → størrelses-partial, ellers None."""
    p = _product_ld(html)
    if not p:
        return None
    brand = "Asics"
    b = p.get("brand")
    if isinstance(b, list) and b and isinstance(b[0], dict):
        brand = b[0].get("name") or brand
    elif isinstance(b, dict):
        brand = b.get("name") or brand

    name = (p.get("name") or "").strip()
    # strip merke-prefiks
    rest = re.sub(r"^%s\s+" % re.escape(brand), "", name, flags=re.I)
    m = NAME_RE.match(rest)
    gender = "unisex"
    if m:
        model = m.group("model").strip()
        gender = _GENDER.get(m.group("gender").lower(), "unisex")
        size = m.group("size")
        color = m.group("color").strip()
    else:
        m = NAME_NOGENDER.match(rest)
        if not m:
            return None                      # uten størrelse kan vi ikke plassere i grid
        model = m.group("model").strip()
        size = m.group("size")
        color = m.group("color").strip()

    off = p.get("offers") or {}
    if isinstance(off, list):
        off = off[0] if off else {}
    price = None
    if off.get("price"):
        try:
            price = int(round(float(off["price"])))
        except (TypeError, ValueError):
            price = None
    in_stock = "instock" in str(off.get("availability", "")).lower()
    ean = p.get("gtin") or None
    buy_url = off.get("url") or url

    return {
        "_brukas": True,
        "brand": brand or "Asics",
        "model": model or None,
        "gender": gender,
        "color": color or None,
        "size_label": size.replace(",", "."),
        "ean": str(ean) if ean else None,
        "price": price,
        "in_stock": in_stock,
        "url": buy_url,
    }


def aggregate(partials: list[dict]) -> list[dict]:
    """Grupper størrelses-partials på (merke, modell, kjønn, farge) → OfferRecords."""
    groups: dict[tuple, dict] = {}
    for r in partials:
        if not r or not r.get("_brukas") or not r.get("model"):
            continue
        if r.get("gender") == "barn":              # ingen barnesko
            continue
        key = (r["brand"], r["model"], r["gender"], (r.get("color") or "").lower())
        g = groups.setdefault(key, {
            "brand": r["brand"], "model": r["model"], "gender": r["gender"],
            "color": r.get("color"), "prices": [], "urls": [], "urls_instock": [],
            "sizes": {},
        })
        if r.get("price") is not None:
            g["prices"].append(r["price"])
        if r.get("url"):
            g["urls"].append(r["url"])
            if r.get("in_stock"):
                g["urls_instock"].append(r["url"])
        # dedup størrelse i colorway; foretrekk på-lager
        s = g["sizes"].get(r["size_label"])
        if s is None or (r.get("in_stock") and not s["in_stock"]):
            g["sizes"][r["size_label"]] = {
                "size_label": r["size_label"], "ean": r.get("ean"),
                "in_stock": bool(r.get("in_stock")), "stock_count": None,
            }

    out = []
    for g in groups.values():
        def _num(x):
            try:
                return float(x["size_label"])
            except ValueError:
                return 999.0
        sizes = sorted(g["sizes"].values(), key=_num)
        url = (g["urls_instock"] or g["urls"] or [""])[0]
        out.append({
            "store": {"slug": "brukas", "name": "Brukås Sport", "source": "scrape", "network": None},
            "brand": g["brand"], "model": g["model"], "gender": g["gender"],
            "product_line": None, "category": "running", "color": g["color"],
            "manufacturer_code": None,        # EAN-matchet, som XXL
            "image_url": None, "store_sku": None, "url": url,
            "currency": "NOK",
            "price": min(g["prices"]) if g["prices"] else None,
            "sizes": sizes,
        })
    return out
