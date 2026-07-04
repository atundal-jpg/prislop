"""
foss_parser.py — parser Foss Sport-PDP (Demonstrare/Multicase).

Hver PDP er én colorway og bærer en JSON-LD `ProductGroup` med `hasVariant[]`,
der hver størrelse har `gtin13` (EAN), `size`, `sku` og `offers` (availability +
pris). Vi leser hele størrelses-raden rett fra JSON-LD-en — ingen HTML-skraping
av variant-velgeren. Returnerer ÉN OfferRecord per colorway (ingen aggregate).

Bro: per-størrelse-EAN (mot XXL/Löplabbet/Brukås) + Asics-stilkode fra bildet
(mot Bull/Intersport). Størrelse beholdes som rå komma («37,5») for å matche XXL.

Filtre: kun løpe-/terrengsko (sitemap-en under /asics/ inneholder også klær,
sokker, tights osv.), og ingen barn (PS/GS/TS/TD eller Barn/Junior).
"""

from __future__ import annotations
import html as _html
import json
import re

LDJSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
# Asics-stilkode i bilde-filnavn: «…/1012b937_700_sr_rt_glb.w720.jpg» -> «1012B937-700»
CODE_RE = re.compile(r"/(\d{4}[A-Za-z]\d{3})_(\d{2,3})_", re.I)
# farge-tail i description: «Terrengsko med godt grep - RD/SC» -> «RD/SC»
COLOR_RE = re.compile(r"-\s*([A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?)\s*$")
SHOE_RE = re.compile(r"(løpe|terreng|jogge|konkurranse|trail)sko", re.I)
KIDS_RE = re.compile(r"\b(PS|GS|TS|TD)\b")
SIZE_TAIL_RE = re.compile(r"\s+\d{1,2}(?:[.,]\d)?H?\s*$")
GENDER_RE = re.compile(r"^(Herre|Dame|Unisex|Barn|Junior)\b\s*", re.I)
CAT_RE = re.compile(r"^(Løpesko|Terrengsko|Joggesko|Konkurransesko|Trailsko|Sko)\b\s*", re.I)

_GENDER = {"herre": "herre", "dame": "dame", "unisex": "unisex",
           "barn": "barn", "junior": "barn"}


def _txt(s) -> str:
    return _html.unescape(str(s or "")).strip()


def _in_stock(offers) -> bool:
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    avail = (offers or {}).get("availability") or ""
    return "instock" in avail.lower() if avail else True   # listet variant uten avail = på lager


def _product_group(html: str) -> dict | None:
    for blk in LDJSON.findall(html):
        try:
            data = json.loads(blk)
        except Exception:
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict) and it.get("@type") == "ProductGroup":
                return it
    return None


def parse(html: str, url: str) -> list[dict]:
    """-> [OfferRecord] for en sko-colorway, eller [] for ikke-sko/barn/ugyldig."""
    grp = _product_group(html)
    if not grp:
        return []

    name = _txt(grp.get("name"))
    if not SHOE_RE.search(name):
        return []                      # jakke/tights/sokker/topp osv. — ikke en sko

    # navn: «Asics <Kjønn> <Kategori> <Modell> <Størrelse>»
    s = re.sub(r"^\s*Asics\s+", "", name, flags=re.I)
    gm = GENDER_RE.match(s)
    gender = _GENDER.get((gm.group(1).lower() if gm else ""), "unisex")
    if gm:
        s = s[gm.end():]
    cm = CAT_RE.match(s)
    if cm:
        s = s[cm.end():]
    model = SIZE_TAIL_RE.sub("", s).strip()
    if not model:
        return []

    if gender == "barn" or KIDS_RE.search(model):
        return []                      # barnesko ute (som XXL/Torshov)

    desc = _txt(grp.get("description"))
    cmcol = COLOR_RE.search(desc)
    color = cmcol.group(1) if cmcol else None

    code = None
    cmatch = CODE_RE.search(grp.get("image") or "")
    if cmatch:
        code = "%s-%s" % (cmatch.group(1).upper(), cmatch.group(2))

    top_off = grp.get("offers") or {}
    if isinstance(top_off, list):
        top_off = top_off[0] if top_off else {}
    price = top_off.get("price")

    sizes, seen = [], set()
    for v in grp.get("hasVariant") or []:
        if not isinstance(v, dict):
            continue
        size = _txt(v.get("size"))
        if not size or size in seen:
            continue
        seen.add(size)
        sizes.append({
            "size_label": size,                 # rå komma, matcher XXL
            "ean": v.get("gtin13"),
            "in_stock": _in_stock(v.get("offers")),
            "stock_count": None,
        })

    if not sizes:
        return []

    product_line = re.sub(r"\s*\d+.*$", "", model).strip().lower().replace(" ", "-") or None
    return [{
        "store": {"slug": "foss", "name": "Foss Sport", "source": "scrape", "network": None},
        "brand": "Asics", "model": model, "gender": gender,
        "product_line": product_line, "category": "running",
        "color": color, "manufacturer_code": code,
        "image_url": None,
        "store_sku": str(grp.get("productGroupID")) if grp.get("productGroupID") else None,
        "url": url, "currency": "NOK",
        "price": price, "original_price": None,
        "sizes": sizes,
    }]
