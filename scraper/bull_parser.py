"""
bull_parser.py — parser produktsider hos Bull Ski & Kajakk (Drupal Commerce 2).

Alt vi trenger ligger i server-HTML (ingen JS):
  - og:title -> modell + (ev.) kjønn; <title>-prefiks -> merke.
  - colorway-kode (full, m/ farge-suffiks): primært fra og:image-filnavnet
    (.../product_image/1011b867-023-...jpg), ellers «Produktnummer: 1011B867-101».
  - Farge: «Farge: COBALT BURST/LIGHT ORANGE».
  - Pris: «1 399,-».
  - STØRRELSER med per-størrelse lager fra <select>: «37.5» = på lager,
    «36 -- Ikke på lager» = utsolgt. (Ingen per-størrelse EAN hos Bull; vi matcher
    på colorway-koden, som er lik formatet hos Intersport/Sport 1.)

parse(html, url) -> OfferRecord (loader.load-kompatibel).
"""
from __future__ import annotations
import re

OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"', re.I)
OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title>([^<|]+)", re.I)
# Full Asics colorway-kode: 4 siffer + bokstav + 3 siffer + «-» + 2-3 siffer.
CODE_RE = re.compile(r"(\d{4}[A-Za-z]\d{3}-\d{2,3})")
CODE_IMG_RE = re.compile(r"/product_image/(\d{4}[a-z]\d{3}-\d{2,3})", re.I)
# Asics-farger er VERSALER («BLACK/NEW LEAF»). Versal-krav avviser bærekraft-
# blurben («prosess som reduserer vannforbruk…») som tidligere ble fanget.
FARGE_RE = re.compile(
    r"Farge\s*:?\s*(?:<[^>]*>\s*){0,3}([A-ZÆØÅ][A-ZÆØÅ0-9/ .&'’-]{2,40})")
# Asics barnesko-markører: GS (grade school) / PS (pre school) / TS (toddler).
KIDS_RE = re.compile(r"\b(?:GS|PS|TS)\b")
PRICE_RE = re.compile(r"(\d[\d\s\u00a0]{2,7})\s*,-")
SELECT_RE = re.compile(r"<select[^>]*>(.*?)</select>", re.S | re.I)
OPTION_RE = re.compile(r"<option[^>]*>([^<]+)</option>", re.I)

_GENDERS = {"herre": "herre", "dame": "dame", "unisex": "unisex",
            "barn": "barn", "junior": "barn"}


def _model_gender(og_title: str) -> tuple[str, str | None]:
    """«Gel-Kayano 31 Herre» -> («Gel-Kayano 31», «herre»). Kjønn er valgfritt;
    loaderens split_model_gender renser uansett til slutt."""
    t = (og_title or "").strip()
    parts = t.split()
    gender = None
    if parts and parts[-1].lower() in _GENDERS:
        gender = _GENDERS[parts[-1].lower()]
        t = " ".join(parts[:-1]).strip()
    return t, gender


def _sizes(html: str) -> list[dict]:
    sizes = []
    for sel in SELECT_RE.findall(html):
        opts = [o.strip() for o in OPTION_RE.findall(sel)]
        # riktig <select> er den med tallstørrelser
        if not any(re.match(r"\d{2}([.,]\d)?", o) for o in opts):
            continue
        for o in opts:
            if not o or "velg" in o.lower():           # «- Velg størrelse -»
                continue
            label = re.split(r"\s*--\s*", o)[0].strip()
            if not re.match(r"\d{2}([.,]\d)?$", label):
                continue
            in_stock = "ikke på lager" not in o.lower()
            sizes.append({
                "size_label": label.replace(",", "."),
                "ean": None,                            # Bull har ikke per-størrelse EAN
                "in_stock": in_stock,
                "stock_count": None,                    # kun binær lagerstatus
            })
        break
    return sizes


def parse(html: str, url: str = "") -> dict | None:
    og_title = (OG_TITLE_RE.search(html) or [None, ""])[1] if OG_TITLE_RE.search(html) else ""
    if KIDS_RE.search((og_title or "").upper()):
        return None                       # barnesko (GS/PS/TS) — utenfor scope
    model, gender = _model_gender(og_title)

    # merke fra <title>-prefiks («ASICS Gel-Kayano 31 …»), ellers Asics
    brand = "Asics"
    tm = TITLE_RE.search(html)
    if tm:
        first = tm.group(1).strip().split()
        if first and first[0].isupper() and len(first[0]) > 1:
            brand = first[0].capitalize()

    # colorway-kode: og:image-filnavn først (mest pålitelig), så «Produktnummer», så fri-tekst
    code = None
    im = OG_IMAGE_RE.search(html)
    if im and (cm := CODE_IMG_RE.search(im.group(1))):
        code = cm.group(1).upper()
    if not code:
        pm = re.search(r"Produktnummer[^0-9]{0,40}?" + CODE_RE.pattern, html, re.I)
        if pm:
            code = pm.group(1).upper()
    if not code and (cm := CODE_RE.search(html)):
        code = cm.group(1).upper()

    color = None
    fm = FARGE_RE.search(html)
    if fm:
        color = re.sub(r"\s+", " ", fm.group(1)).strip().title()

    price = None
    pm = PRICE_RE.search(html)
    if pm:
        price = int(re.sub(r"[\s\u00a0]", "", pm.group(1)))

    og_img = im.group(1) if im else None

    sizes = _sizes(html)
    if not code and not sizes:
        return None                       # ingen kode + ingen størrelse = umatchbar (utsolgt)

    return {
        "store": {"slug": "bull", "name": "Bull Ski & Kajakk", "source": "scrape", "network": None},
        "brand": brand or "Asics",
        "model": model or None,
        "gender": gender or "unisex",
        "product_line": None,
        "category": "running",
        "color": color,
        "manufacturer_code": code,
        "image_url": og_img,
        "store_sku": code,
        "url": url,
        "currency": "NOK",
        "price": price,
        "sizes": sizes,
    }


if __name__ == "__main__":
    import sys, json
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    rec = parse(html, sys.argv[2] if len(sys.argv) > 2 else "")
    print(json.dumps({k: v for k, v in rec.items() if k != "sizes"}, ensure_ascii=False, indent=1))
    for s in rec["sizes"]:
        print(f"  {s['size_label']:>5}  in_stock={s['in_stock']}")
