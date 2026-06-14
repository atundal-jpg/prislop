"""
normalize.py — matching-/normaliseringshjernen for Prisløp.

To nivåer, som mater rett inn i «bredt vs smalt» i UI-et:

  1) PRODUKT (bredt): kanonisk nøkkel fra (merke, modell, kjønn).
     Navne-normalisering trengs her fordi noen butikker mangler kode
     (f.eks. XXL gir bare EAN), så navnet er det som forener dem med de
     kode-baserte butikkene under ett produkt.

  2) FARGEVEI / variant (smalt, nedtrekk): identifiseres på
     produsentkode (Asics-kode) når den finnes, ellers på EAN-overlapp,
     ellers på normalisert fargenavn. Butikkenes egne fargenavn beholdes
     som ALIAS — slik at nedtrekket viser én ren fargevei i stedet for
     «Blå» og «Lilla/Blå» som to.

Den autoritative kryssnøkkelen mellom butikker er ALLTID kode/EAN.
Navne-normaliseringen er en heuristikk for å forene de kodeløse.
"""

from __future__ import annotations
import re, itertools

# --- Produkt-normalisering -------------------------------------------------

# Asics "gel-"linjer som butikker noen ganger skriver uten "gel-"-prefiks.
_GEL_LINES = {"nimbus", "kayano", "cumulus", "pulse", "excite", "trabuco", "venture"}

_BRAND_FIX = {"asics": "Asics", "nike": "Nike", "adidas": "adidas",
              "new balance": "New Balance", "hoka": "Hoka", "brooks": "Brooks",
              "saucony": "Saucony", "mizuno": "Mizuno", "puma": "Puma"}

_GENDER_FIX = {"herre": "herre", "menn": "herre", "men": "herre",
               "dame": "dame", "kvinne": "dame", "women": "dame",
               "unisex": "unisex", "barn": "barn", "junior": "barn", "jr": "barn"}


def norm_brand(brand: str) -> str:
    b = (brand or "").strip().lower()
    return _BRAND_FIX.get(b, brand.strip().title() if brand else "")


def norm_gender(g: str) -> str:
    return _GENDER_FIX.get((g or "").strip().lower(), (g or "unisex").strip().lower())


def norm_model(model: str) -> str:
    """Kanonisk, sammenlignbar modellstreng: lower, samlede skilletegn,
    og legg på 'gel-' der en bar Asics-linje er skrevet uten det."""
    m = (model or "").lower()
    m = re.sub(r"[\-/]", " ", m)
    m = re.sub(r"\s+", " ", m).strip()
    toks = m.split(" ")
    # "nimbus 27" -> "gel-nimbus 27"
    if toks and toks[0] in _GEL_LINES:
        toks[0] = "gel-" + toks[0]
    elif len(toks) >= 2 and toks[0] == "gel" and toks[1] in _GEL_LINES:
        toks = ["gel-" + toks[1]] + toks[2:]
    return " ".join(toks)


def product_key(brand: str, model: str, gender: str) -> tuple:
    """Nøkkelen som forener samme sko på tvers av butikker (også kodeløse)."""
    return (norm_brand(brand).lower(), norm_model(model), norm_gender(gender))


# --- Fargevei-/variantoppløsning -------------------------------------------

def colorway_stem(code: str | None) -> str | None:
    """Asics-kode '1011B958-500' -> stamme '1011B958' (modell+spec, uten farge)."""
    if not code:
        return None
    m = re.match(r"^([0-9A-Za-z]+)-\d+$", code.strip())
    return m.group(1) if m else code.strip()


class Colorway:
    """En kanonisk fargevei: kode (om kjent), sett av EAN-er, og navne-alias."""
    _ids = itertools.count(1)

    def __init__(self, code=None, eans=None, name=None):
        self.id = next(self._ids)
        self.code = code
        self.eans = set(eans or [])
        self.names = set([name]) if name else set()

    def merge_in(self, code, eans, name):
        if code and not self.code:
            self.code = code            # arve kode fra butikk som har den
        self.eans |= set(eans or [])
        if name:
            self.names.add(name)

    def __repr__(self):
        return f"Colorway(code={self.code}, names={sorted(self.names)}, eans={len(self.eans)})"


def resolve_colorway(record: dict, existing: list[Colorway]) -> Colorway:
    """Plasser et innkommende tilbud i riktig kanonisk fargevei.
    record: {manufacturer_code, eans:[...], color}
    Prioritet: kode -> EAN-overlapp -> ny."""
    code = record.get("manufacturer_code")
    eans = set(record.get("eans") or [])
    name = record.get("color")

    # 1) match på kode
    if code:
        for cw in existing:
            if cw.code and cw.code == code:
                cw.merge_in(code, eans, name)
                return cw
    # 2) match på EAN-overlapp
    if eans:
        for cw in existing:
            if cw.eans & eans:
                cw.merge_in(code, eans, name)
                return cw
    # 3) ny fargevei
    cw = Colorway(code=code, eans=eans, name=name)
    existing.append(cw)
    return cw
