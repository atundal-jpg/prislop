"""
oslosportslager_parser.py — parser Oslo Sportslager-PDP (.aspx, intern plattform).

Hver PDP er ÉTT produkt-ID, men bærer ALLE fargevarianter (colorways) og alle
størrelser per colorway i ett rått JSON-blob i en <script>-tag:
    let b = {"Hits":1,"Offset":0,"Product":[{...}]};
Ikke JSON-LD — en JS-variabel-tildeling. Trekkes ut med
json.JSONDecoder().raw_decode() rett etter "let b = " (robust mot hva som
helst av etterfølgende JS-setninger/kommentarer — se probe_oslosportslager v4).

Product["Details"] er en liste av lister: Details[0] er en type-beskrivelse
(Type1D/Unit1D, ingen Id/GTIN) og skal hoppes over. Details[1:] er én liste
per fargevariant — første element er fargemetadata (Color/ColorId/Pic),
resten er størrelser:
    {"Id": 293022, "Qty": 3, "GTIN": [4550215825487], "Size": "37"}
Qty er EKSAKT lagerantall (ikke bare på lager/utsolgt) — rikere bro-data enn
de fleste andre butikkene i katalogen.

Pris: SRP (veiledende), MP (medlemspris), LP (listepris) — alle i øre. Vi
bruker LP: MP krever innlogging og er ikke prisen en anonym besøkende faktisk
ser/kan handle til via /ut-redirecten.

Header-feltet («Gel-Nimbus 22, løpesko dame») bærer modell + kategori/kjønn
etter SISTE komma — enklere enn foss_parser sin strip-løkke siden rekke-
følgen her er fast (modell, kategori kjønn).

Bro: per-størrelse-EAN (GTIN) mot de andre butikkene. Ingen produsent-
stilkode synlig i dataene, så manufacturer_code er alltid None (som XXL).

Filtre: kun løpe-/terrengsko (Header må inneholde et sko-kategoriord —
merke-/kategorikoder som Fedas varierer for mye til å være et pålitelig
filter alene, så Header-teksten er sannheten, som i foss_parser), og ingen
barn (barn/junior i kjønnsteksten, eller PS/GS/TS/TD i modellnavnet).
"""

from __future__ import annotations
import html as _html
import json
import re

BLOB_MARK = "let b = "

SHOE_RE = re.compile(r"(løpe|terreng|fjell|jogge|trail|konkurranse)sko", re.I)
KIDS_RE = re.compile(r"\b(PS|GS|TS|TD)\b")
_GENDER_WORDS = [("dame", "dame"), ("herre", "herre"), ("unisex", "unisex"),
                 ("junior", "barn"), ("barn", "barn")]


def _txt(s) -> str:
    return _html.unescape(str(s or "")).strip()


def _extract_blob(html: str) -> dict | None:
    idx = html.find(BLOB_MARK)
    if idx < 0:
        return None
    start = idx + len(BLOB_MARK)
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, start)
    except (ValueError, json.decoder.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _parse_header(header) -> tuple[str, str] | None:
    """-> (model, gender), eller None hvis Header ikke ser ut som en sko."""
    header = _txt(header)
    if not header:
        return None
    model, _, tail = header.rpartition(",")
    model = model.strip() or header
    tail = tail.strip() or header
    if not SHOE_RE.search(tail) and not SHOE_RE.search(header):
        return None
    gender = "unisex"
    for word, g in _GENDER_WORDS:
        if re.search(r"\b%s\b" % word, tail, re.I):
            gender = g
            break
    return model, gender


def _colorways(details) -> list[tuple[dict, list[dict]]]:
    """Details[0] er en type-beskrivelse uten Id/GTIN — hoppes over.
    Details[1:]: [fargemeta, størrelse1, størrelse2, ...] per fargevariant."""
    out = []
    for sub in (details or [])[1:]:
        if not isinstance(sub, list):
            continue
        meta, sizes = None, []
        for item in sub:
            if not isinstance(item, dict):
                continue
            if "GTIN" in item or "Qty" in item:
                sizes.append(item)
            elif meta is None:
                meta = item
        if sizes:
            out.append((meta or {}, sizes))
    return out


def parse(html: str, url: str) -> list[dict]:
    """-> [OfferRecord] — én per fargevariant på siden, eller [] for
    ikke-sko/barn/ugyldig/manglende blob."""
    blob = _extract_blob(html)
    if not blob:
        return []

    out = []
    for product in blob.get("Product") or []:
        if not isinstance(product, dict):
            continue

        parsed = _parse_header(product.get("Header"))
        if not parsed:
            continue                      # ikke en sko (Fedas/slug kan ta feil, Header er sannhet)
        model, gender = parsed
        if gender == "barn" or KIDS_RE.search(model):
            continue                      # barnesko ute (som Foss/Torshov/XXL)

        brand = _txt(product.get("BrandName"))
        if not brand:
            continue                      # uten merke kan vi ikke plassere produktet

        product_id = product.get("ProductId")
        lp = product.get("LP")
        price = round(lp / 100.0, 2) if isinstance(lp, (int, float)) else None

        product_line = re.sub(r"\s*\d+.*$", "", model).strip().lower().replace(" ", "-") or None

        for meta, sizes in _colorways(product.get("Details")):
            color = _txt(meta.get("Color")) or None
            color_id = meta.get("ColorId")

            rows, seen = [], set()
            for s in sizes:
                label = _txt(s.get("Size"))
                if not label or label in seen:
                    continue
                seen.add(label)
                gtin = s.get("GTIN")
                ean = str(gtin[0]) if isinstance(gtin, list) and gtin else None
                qty = s.get("Qty")
                qty = qty if isinstance(qty, int) else None
                rows.append({
                    "size_label": label,
                    "ean": ean,
                    "in_stock": bool(qty and qty > 0),
                    "stock_count": qty,
                })
            if not rows:
                continue

            store_sku = (f"{product_id}-{color_id}" if product_id and color_id
                         else (str(product_id) if product_id else None))

            out.append({
                "store": {"slug": "oslosportslager", "name": "Oslo Sportslager",
                          "source": "scrape", "network": None},
                "brand": brand, "model": model, "gender": gender,
                "product_line": product_line, "category": "running",
                "color": color, "manufacturer_code": None,
                "image_url": None,
                "store_sku": store_sku,
                "url": url, "currency": "NOK",
                "price": price,
                "sizes": rows,
            })
    return out
