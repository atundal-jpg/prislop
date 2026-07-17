"""
olympia_parser.py — parser produktsider hos Olympia Sport (nopCommerce-aktig
egen-plattform, server-rendret).

Ett PDP-fetch = ÉN fargevei MED alle størrelser (ikke én side per størrelse
som Brukås) — "Velg variant"-knappegridet lister alle data-productid-er for
colorwayen, og hver av dem har egne pris-/lager-/SKU-blokker allerede i den
statiske HTML-en (RenderProductDetails i klienten bare BYTTER hvilken av dem
som vises, laster ikke noe via AJAX — verifisert i probe_olympia_ajax og
probe_olympia_sizeblocks):
  - modell (uten farge): <h1>.
  - farge: og:title MINUS h1-prefikset (og:title har farge-halen, h1 ikke).
  - kjønn: <div class="productGender">…Modell: </span>DAME/HERRE</div> —
    allerede norsk, mer pålitelig enn å lete etter Womens/Mens i tittelen.
  - merke: "Se mer fra"-lenken i .manufacturers-blokken.
  - produsentkode (MPN): itemprop="mpn" / id="mpn-<id>" — samme kode-FORMAT
    som Adidas/Saucony sin egen artikkelkode hos Intersport/Sport1 (probe_
    olympia_bridge), men IKKE bekreftet identisk kode for samme fysiske sko
    (0/8 direkte treff i den proben) — brukes derfor kun som Olympias EGEN
    manufacturer_code. Loaderens selvhelbredende kode-arv (get_or_create_variant
    i loader.py) fanger opp ekte overlapp automatisk hvis/når den finnes.
  - EAN: finnes ALDRI (probe_olympia_ajax: itemprop="gtin" er bevisst tomt på
    hver eneste sjekket PDP) — sizes[].ean er alltid None. Broen til andre
    butikker skjer derfor kun via manufacturer_code eller navnematching
    (normalize.product_key), akkurat som XXL/Oslo Sportslager.
  - pris/lager per størrelse: id="price-value-<id>" / id="stock-availability-
    value-<id>" / tilstedeværelse av id="add-to-cart-button-<id>".
  - butikk-artikkelnummer (colorway-nivå store_sku): id="sku-<parent-id>"
    inneholder "<tall>PARENT" for produktets grunn-id (ikke en av de valgbare
    størrelsene) — tallet uten PARENT-suffikset er den stabile colorway-SKU-en.

parse(html, url) -> OfferRecord (loader.load-kompatibel), eller None hvis
siden ikke er en gjenkjennelig løpesko-PDP (mangler h1/variant-grid).
"""
from __future__ import annotations
import re

H1_RE = re.compile(r'<h1\b[^>]*>(.*?)</h1>', re.I | re.S)
OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]*)"', re.I)
OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]*)"', re.I)
MANUFACTURER_RE = re.compile(
    r'class="manufacturers"[^>]*>.*?<a\s+href="/[^"]+"[^>]*>([^<]+)</a>', re.I | re.S)
GENDER_DIV_RE = re.compile(
    r'class="productGender"[^>]*>.*?Modell:\s*</span>\s*([^<]+)</div>', re.I | re.S)
MPN_RE = re.compile(r'id="mpn-\d+"[^>]*>([^<]+)<', re.I)
SKU_PARENT_RE = re.compile(r'id="sku-\d+"[^>]*>(\d+)PARENT<', re.I)

BUTTON_TAG_RE = re.compile(r'<input[^>]*class="renderAssProd[^"]*"[^>]*>', re.I)
VALUE_ATTR_RE = re.compile(r'value="([^"]*)"')
PID_ATTR_RE = re.compile(r'data-productid="(\d+)"')

# Prisen sitter enten på id="price-value-<id>" (normalpris — samme span har
# ofte BÅDE id= og class= med identisk verdi), ELLER, for nedsatte varer, KUN
# på class="price-value-<id>" ("Din pris"-spannet mangler id=; den krysset-ut
# originalprisen sitter i et helt umerket <span> uten id/class i det hele
# tatt og fanges derfor aldri av denne regexen — riktig, vi vil ha "Din pris").
PRICE_BY_ID_RE = re.compile(
    r'(?:id="price-value-(\d+)"|class="[^"]*\bprice-value-(\d+)\b[^"]*")'
    r'[^>]*>\s*kr\s*([\d\s ]+?)\s*<', re.I)
ADD_TO_CART_ID_RE = re.compile(r'id="add-to-cart-button-(\d+)"', re.I)

_GENDER_MAP = {"herre": "herre", "dame": "dame", "unisex": "unisex",
               "barn": "barn", "junior": "barn"}
_TRAIL_GENDER_WORD_RE = re.compile(r'\b(Womens|Mens|Unisex)\b\s*$', re.I)


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _buttons(html: str) -> list[tuple[str, str]]:
    """[(productid, størrelsesetikett), ...] fra "Velg variant"-gridet."""
    out = []
    for tag in BUTTON_TAG_RE.findall(html):
        vm, pm = VALUE_ATTR_RE.search(tag), PID_ATTR_RE.search(tag)
        if vm and pm:
            out.append((pm.group(1), vm.group(1)))
    return out


def _prices_by_id(html: str) -> dict[str, int]:
    out = {}
    for m in PRICE_BY_ID_RE.finditer(html):
        pid = m.group(1) or m.group(2)
        digits = re.sub(r"[\s ]", "", m.group(3))
        if pid and digits.isdigit():
            out[pid] = int(digits)
    return out


def parse(html: str, url: str = "") -> dict | None:
    m = H1_RE.search(html)
    if not m:
        return None
    h1 = _clean_text(m.group(1))

    buttons = _buttons(html)
    if not h1 or not buttons:
        return None

    bm = MANUFACTURER_RE.search(html)
    brand = bm.group(1).strip().title() if bm else None

    # merket sitter foran i h1 ("Adidas Supernova Rise 3") — fjern det for
    # å få det rene modellnavnet, uavhengig av om .manufacturers-lenken fantes.
    model = h1
    if brand and model.lower().startswith(brand.lower()):
        model = model[len(brand):].strip()
    model = _TRAIL_GENDER_WORD_RE.sub("", model).strip()

    gm = GENDER_DIV_RE.search(html)
    gender = _GENDER_MAP.get((gm.group(1).strip().lower() if gm else ""), "unisex")

    color = None
    ogt = OG_TITLE_RE.search(html)
    if ogt:
        og_title = ogt.group(1).strip()
        if og_title.lower().startswith(h1.lower()):
            color = og_title[len(h1):].strip(" /") or None

    mpn_m = MPN_RE.search(html)
    mpn = mpn_m.group(1).strip() if mpn_m else None

    sku_m = SKU_PARENT_RE.search(html)
    store_sku = sku_m.group(1) if sku_m else mpn

    prices = _prices_by_id(html)
    in_stock_ids = set(ADD_TO_CART_ID_RE.findall(html))

    sizes = []
    for pid, label in buttons:
        sizes.append({
            "size_label": label.replace(",", "."),
            "ean": None,                       # Olympia eksponerer aldri EAN/GTIN
            "in_stock": pid in in_stock_ids,
            "stock_count": None,               # kun binær lagerstatus
        })

    price_values = [prices[pid] for pid, _ in buttons if pid in prices]
    price = min(price_values) if price_values else None

    og_img = OG_IMAGE_RE.search(html)

    return {
        "store": {"slug": "olympia", "name": "Olympia Sport", "source": "scrape", "network": None},
        "brand": brand or "",
        "model": model or None,
        "gender": gender,
        "product_line": None,
        "category": "running",
        "color": color,
        "manufacturer_code": mpn,
        "image_url": og_img.group(1) if og_img else None,
        "store_sku": store_sku,
        "url": url,
        "currency": "NOK",
        "price": price,
        "sizes": sizes,
    }


if __name__ == "__main__":
    import sys, json
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    rec = parse(html, sys.argv[2] if len(sys.argv) > 2 else "")
    if rec is None:
        print("Ikke gjenkjent som PDP.")
    else:
        print(json.dumps({k: v for k, v in rec.items() if k != "sizes"}, ensure_ascii=False, indent=1))
        for s in rec["sizes"]:
            print(f"  {s['size_label']:>7}  in_stock={s['in_stock']}")
