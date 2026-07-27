"""
bull_parser.py — parser produktsider hos Bull Ski & Kajakk (Drupal Commerce 2).

Alt vi trenger ligger i server-HTML (ingen JS):
  - og:title -> modell + (ev.) kjønn; <title>-prefiks -> merke.
  - colorway-kode (full, m/ farge-suffiks): primært fra og:image-filnavnet
    (.../product_image/1011b867-023-...jpg eller …-1147911-cslp-5.jpg),
    ellers «Produktnummer: 1011B867-101» (Asics) / «Art#: 1147911-CSLP» (Hoka).
    Kodeformatet er MERKEAVHENGIG — se CODE_RE. adidas har ingen kode-etikett
    på siden i det hele tatt; der ligger koden bare i og:image-filnavnet.
  - store_sku: colorway-koden når vi finner den, ellers JSON-LD `sku` (GTIN).
    Feltet skal ALDRI være None for en side vi emitter — det er loaderens
    eneste sterke nøkkel hos Bull (ingen per-størrelse EAN), og en NULL her
    ga 5 931 duplikatrader mellom 18. og 27. juli (se CODE_RE-notatet).
  - Farge: «Farge: COBALT BURST/LIGHT ORANGE».
  - Pris: «1 399,-».
  - STØRRELSER med per-størrelse lager fra <select>: «37.5» = på lager,
    «36 -- Ikke på lager» = utsolgt. Hoka bruker tredjedeler («42 2/3»). (Ingen per-størrelse EAN hos Bull; vi matcher
    på colorway-koden, som er lik formatet hos Intersport/Sport 1.)

parse(html, url) -> OfferRecord (loader.load-kompatibel).
"""
from __future__ import annotations
import json
import re

OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"', re.I)
OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"', re.I)
TITLE_RE = re.compile(r"<title>([^<|]+)", re.I)
# Fulle colorway-koder. Formatene er MERKEAVHENGIGE og lest ut av ekte markup
# med probe_bull_sku.py (27. juli) — ikke gjettet:
#   Asics    «1013A163-400»  4 siffer + bokstav + 3 siffer + «-» + 2-3 siffer
#   Hoka     «1168691-BWHT»  7 siffer + «-» + bokstaver
#   Kiprun   «369831-PINK»   6 siffer + «-» + bokstaver
#   Saucony  «S100981-1021»  bokstav + 5-6 siffer + «-» + 3-4 siffer
#            «S21023-200»    — Saucony har TO kodelengder, se under
# (adidas har ingen slik kode på siden — se ADIDAS_CODE_IMG_RE.)
#
# Hvorfor dette ble en bug: PR #18 la Saucony, adidas og Kiprun til i
# discovery.by_brand uten at parseren lærte kodeformatene deres. store_sku ble
# NULL for de merkene, og siden Bull hverken har produsentkode eller
# per-størrelse EAN i markupen sto loaderen igjen uten nøkkel og laget ny
# variant + nytt tilbud ved HVER kjøring: 6 441 rader for 663 URL-er, +155 per
# harvest. Stikkprøvene i PR #18 dekket pris og URL, ikke store_sku.
#
# (?<!\d) beholdes: den hindrer at halen av et lengre tall (EAN/GTIN) matcher
# siffer-alternativene. Saucony-alternativet har i tillegg (?<![A-Za-z]) så det
# ikke kan starte midt i et ord.
#
# Saucony-lengdene (rettet 27. juli, probe_bull_code_source): merket bruker TO
# formater — «S100981-1021» (6+4) på Endorphin-linja og «S21023-200» (5+3) på
# Triumph/Peregrine/Ride/Xodus. Første versjon dekket bare 6+4. Sidene med 5+3
# har HVERKEN «Produktnummer»-etikett, så begge de forankrede kildene bommet,
# og koden ble hentet av fri-tekst-grenen — fra «Relaterte produkter»-
# karusellen. Resultat: en Saucony CAPS-kode (2632400-SHAKEOUT) sto på fem
# ulike sko, en HATT-kode (1170330-BLK) på fire, en quarter-zip-kode
# (1164155-TLS) på både en Saucony- og en Kiprun-sko.
_CODE_ALT = (r"\d{4}[A-Za-z]\d{3}-\d{2,3}"                 # Asics
             r"|\d{6,7}-[A-Za-z]{2,8}"                     # Hoka / Kiprun
             r"|(?<![A-Za-z])[A-Za-z]\d{5,6}-\d{3,4}")     # Saucony (5+3 og 6+4)
CODE_RE = re.compile(r"(?<!\d)(" + _CODE_ALT + r")\b")
# Asics-koden står først i og:image-filnavnet; Hoka-koden midt i
# («…alpine-blue-1147911-cslp-5.jpg») — derfor lazy prefiks innen filbanen.
# Saucony ligger også her («…/product_image/s100981-1021-1.jpg»); Kiprun gjør
# det IKKE (bildene heter «kd1200-h-ah25-aw25-8953316-003-….jpg»), og tas av
# «Produktnummer»-etiketten under.
CODE_IMG_RE = re.compile(
    r"/product_image/[^\"'?]*?(?<!\d)(" + _CODE_ALT + r")", re.I)
# adidas: probe_bull_sku fant HVERKEN «Produktnummer», «Art#» eller noe annet
# id-felt i sideteksten — artikkelkoden (2 bokstaver + 4 siffer) finnes bare
# som ledd i og:image-filnavnet: «…-semi-blue-burst-jp8680-photoroom.jpg»,
# «…-carbon-ki6927-photoroom.jpg». Mønsteret er for kort og generisk til å
# slippes løs på rå HTML eller på andre merkers bildenavn (Kiprun-bildene
# starter f.eks. med «kd1200»), så det brukes KUN på og:image og KUN når
# merket er adidas.
ADIDAS_CODE_IMG_RE = re.compile(
    r"/product_image/[^\"'?]*?-([A-Za-z]{2}\d{4})(?=[-.])", re.I)
# Asics-farger er VERSALER («BLACK/NEW LEAF»). Versal-krav avviser bærekraft-
# blurben («prosess som reduserer vannforbruk…») som tidligere ble fanget.
FARGE_RE = re.compile(
    r"Farge\s*:?\s*(?:<[^>]*>\s*){0,3}([A-ZÆØÅ][A-ZÆØÅ0-9/ .&'’-]{2,40})")
# Asics barnesko-markører: GS (grade school) / PS (pre school) / TS (toddler).
KIDS_RE = re.compile(r"\b(?:GS|PS|TS)\b")
# PRIS (fikset 10. juli): gammelt mønster tok FØRSTE «tall,-» i HTML-en —
# som er det sidefaste fraktbanneret «Fri frakt fra 1399,- *» øverst på alle
# Bull-sider. Alle 160 tilbud sto derfor med 1399 uansett faktisk pris
# (avdekket via klikk-redirecten; probe_bull_price.py bekreftet markupen).
# Primærkilde nå: JSON-LD offers.price (ren salgspris, f.eks. "1840").
# Fallback: første <div class="current …"> i product-price-blokken — den
# hører til hovedproduktet; «andre kjøpte også»-karusellen kommer senere.
PRICE_CURRENT_RE = re.compile(
    r'class="current[^"]*"\s*>\s*(?:<strong>\s*)?(\d[\d\s\u00a0]{0,7}),-', re.I)
LD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
# Skillelinje mot tilbehørs-karusellen nederst på siden — alt etter denne
# tilhører ANDRE produkter og skal aldri brukes som kilde til denne sidens kode.
RELATED_RE = re.compile(r"Relaterte\s+produkter", re.I)


def _ld_price(html: str) -> int | None:
    """Salgspris fra JSON-LD (Product -> offers.price)."""
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        if not isinstance(nodes, list):
            nodes = [nodes]
        for n in nodes:
            if not (isinstance(n, dict) and n.get("@type") == "Product"):
                continue
            off = n.get("offers") or {}
            if isinstance(off, list):
                off = off[0] if off else {}
            p = off.get("price")
            if p:
                try:
                    return int(round(float(p)))
                except (TypeError, ValueError):
                    pass
    return None


GTIN_RE = re.compile(r"^\d{8,14}$")


def _ld_sku(html: str) -> str | None:
    """GTIN fra JSON-LD (Product -> sku). Backstop for store_sku når vi ikke
    kjenner merkets kodeformat: alle fem merkene hos Bull har dette feltet, og
    det er distinkt per fargevariant (probe 27. juli: Endorphin Elite 3 sto med
    195022001088 og 195022000630 på hver sin farge-URL).

    Poenget er strukturelt, ikke kosmetisk: så lenge store_sku er satt, kan
    loaderen kjenne igjen raden neste kjøring. Det er bevisst et ANNET felt enn
    manufacturer_code — GTIN-en er butikk-lokal identitet (offers.store_sku),
    mens manufacturer_code brukes til å slå sammen samme fargevei på TVERS av
    butikker og skal derfor bare settes når vi har den ekte colorway-koden."""
    for m in LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data
        if not isinstance(nodes, list):
            nodes = [nodes]
        for n in nodes:
            if not (isinstance(n, dict) and n.get("@type") == "Product"):
                continue
            sku = str(n.get("sku") or "").strip()
            if GTIN_RE.match(sku):
                return sku
    return None


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
            label = re.sub(r"\s+", " ", re.split(r"\s*--\s*", o)[0].strip())
            # hel («42»), halv («42.5»/«42,5») eller tredjedel («42 2/3» —
            # Hoka). Tredjedeler beholder mellomrom+brøk, samme konvensjon
            # som Löplabbet/Oslo Sportslager, så størrelsene matcher på tvers
            # av butikker. (Før 18. juli falt tredjedeler ut her — Bull-Hoka
            # sto da kun med helstørrelser i katalogen.)
            if not re.match(r"\d{2}([.,]\d|\s[12]/3)?$", label):
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
    if not code and im and brand.lower() == "adidas":
        if am := ADIDAS_CODE_IMG_RE.search(im.group(1)):
            code = am.group(1).upper()
    if not code:
        # Asics-sider merker koden «Produktnummer:», Hoka-sider «Art#:»
        pm = re.search(r"(?:Produktnummer|Art\s*#)[^0-9]{0,40}?" + CODE_RE.pattern,
                       html, re.I)
        if pm:
            code = pm.group(1).upper()
    if not code:
        # Siste utvei: fri tekst — men KUN i hoveddelen av dokumentet.
        # «Relaterte produkter»-karusellen nederst er full av tilbehør
        # (caps, hatter, quarter-zip) med kode-formede filnavn, og et
        # uforankret søk i hele HTML-en plukket dem systematisk opp så snart
        # de forankrede kildene bommet (27. juli, probe_bull_code_source).
        # Samme klasse feil som fraktbanneret: aldri første regex-treff i rå
        # HTML uten å vite hvilken blokk man står i.
        head = html[:rm.start()] if (rm := RELATED_RE.search(html)) else html
        if cm := CODE_RE.search(head):
            code = cm.group(1).upper()

    color = None
    fm = FARGE_RE.search(html)
    if fm:
        color = re.sub(r"\s+", " ", fm.group(1)).strip().title()

    price = _ld_price(html)
    if price is None:
        pm = PRICE_CURRENT_RE.search(html)
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
        # code først (stabil, delt med Intersport/Sport 1), GTIN som backstop
        # slik at feltet aldri blir NULL — se _ld_sku.
        "store_sku": code or _ld_sku(html),
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
