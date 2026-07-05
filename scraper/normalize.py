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

# Sammensatte linjenavn (camelCase) som noen butikker deler med mellomrom.
# Kollapses så "Fuji Speed 4" og "FujiSpeed 4" matcher samme sko.
_COMPOUNDS = [("fuji speed", "fujispeed"), ("meta speed", "metaspeed"),
              ("meta fuji", "metafuji"), ("fuji setsu", "fujisetsu")]

_BRAND_FIX = {"asics": "Asics", "nike": "Nike", "adidas": "adidas",
              "new balance": "New Balance", "hoka": "Hoka", "brooks": "Brooks",
              "saucony": "Saucony", "mizuno": "Mizuno", "puma": "Puma",
              "kiprun": "Kiprun"}

# Ledende tokens som IKKE er del av modellidentiteten (bølge 2, 5. juli):
#  - merkenavn lekket inn i modellen («Saucony Guide 18», «Nike Pegasus Plus»)
#  - kjønnsbokstaver («M Mach 6», «W Vomero 18», «WMNS Air Winflo 11»)
#  - Nike-markedsføringsprefikser («Air Zoom Pegasus 42», «Zoomx Vaporfly 4»,
#    «Reactx Pegasus Trail 5», «Air Winflo 11»). NB: bare «zoom» strippes
#    ALDRI alene — «Zoom Fly» er et ekte modellnavn («air zoom» tas som par).
_LEAD_BRAND_TOKENS = {"asics", "adidas", "nike", "hoka", "saucony", "puma", "kiprun"}
_LEAD_DROP_TOKENS = {"zoomx", "reactx"}


def _strip_lead_tokens(toks: list[str]) -> list[str]:
    """Fjern ledende merke-/kjønns-/markedsføringstokens (lowercase input).
    Itererer: «nike zoomx zoom fly 6» -> «zoom fly 6»."""
    while toks:
        t = toks[0]
        if t in _LEAD_BRAND_TOKENS or t in _LEAD_DROP_TOKENS or t in _LEAD_GENDER:
            toks = toks[1:]
            continue
        if t == "air":
            toks = toks[2:] if len(toks) >= 2 and toks[1] == "zoom" else toks[1:]
            continue
        break
    return toks


# Trailing tokens som ikke er del av modellidentiteten (DQ-runde 2, 5. juli):
#  - kjønnsbokstav-SUFFIKS («Adizero Boston 12 M», «Supernova Rise W», «Guide 16, W»)
#  - norske beskrivelses-haler («… Piggsko Terreng», «Pegasus Plus Løpeesko»).
#    NB: «trail» strippes ALDRI («Invincible Trail» er et ekte modellnavn) —
#    kun de norske sko-ordene, som aldri er del av et modellnavn.
#  - engelske produktbeskrivelser kuttes fra og med Men's/Women's
#    («Pegasus 42 Men's Road Running Shoes»)
# Token-kart: Löplabbet oversetter Wide->«Bred» (Hoka); Intersport forkorter
# «Jakob Ingebrigtsen»->«Ji» (Nike-signaturmodeller).
_TRAIL_GENDER = {"m", "w", "u", "wmns"}
_TRAIL_NOISE = {"løpesko", "løpeesko", "terrengløpesko", "joggesko",
                "piggsko", "terreng"}
_CUT_FROM = {"men's", "mens", "women's", "womens"}
_TOKEN_MAP = {"bred": "wide", "ji": "jakob ingebrigtsen"}


def _clean_tail_tokens(toks: list[str]) -> list[str]:
    """Kutt ved Men's/Women's, dropp trailing støy-/kjønnstokens (lowercase)."""
    for i, t in enumerate(toks):
        if t in _CUT_FROM:
            toks = toks[:i]
            break
    while len(toks) > 1 and (toks[-1] in _TRAIL_NOISE or toks[-1] in _TRAIL_GENDER):
        toks = toks[:-1]
    return toks

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
    foren Gore-Tex/GTX, kollaps sammensatte navn, og legg på 'gel-' der en
    bar Asics-linje mangler det."""
    m = (model or "").lower()
    m = re.sub(r"[\"'«»„“”|]", "", m)              # anførselstegn/pipe fra butikk-SEO-navn
    m = re.sub(r"[\-/,]", " ", m)
    m = re.sub(r"\s+", " ", m).strip()
    # Gore-Tex == GTX: butikker veksler mellom skrivemåtene (XXL: "Gore-Tex",
    # Intersport/seed: "GTX"). Foren til "gtx" så samme sko matcher på tvers.
    m = re.sub(r"\bgore\s?tex\b", "gtx", m)
    m = re.sub(r"\bg\s?tx\b", "gtx", m)            # G-TX / G TX == GTX (matcher canonical_model)
    # Sammensatte linjenavn som noen butikker deler med mellomrom
    # ("Fuji Speed" vs "FujiSpeed") -> kollaps, ellers splittes samme sko.
    for sp, joined in _COMPOUNDS:
        m = m.replace(sp, joined)
    toks = _strip_lead_tokens(m.split(" "))
    toks = [_TOKEN_MAP.get(t, t) for t in toks]
    toks = _clean_tail_tokens(" ".join(toks).split(" "))
    # "nimbus 27" -> "gel-nimbus 27"
    if toks and toks[0] in _GEL_LINES:
        toks[0] = "gel-" + toks[0]
    elif len(toks) >= 2 and toks[0] == "gel" and toks[1] in _GEL_LINES:
        toks = ["gel-" + toks[1]] + toks[2:]
    return " ".join(toks)


def product_key(brand: str, model: str, gender: str) -> tuple:
    """Nøkkelen som forener samme sko på tvers av butikker (også kodeløse)."""
    return (norm_brand(brand).lower(), norm_model(model), norm_gender(gender))


# --- Visningsnavn (kanonisk casing) ----------------------------------------
# Skilles fra norm_model: norm_model er match-NØKKELEN (lowercase), mens dette
# er det PENE navnet som vises i UI-et. Butikkene skriver navnet rotete
# («GEL-KAYANO 33», «GT-2000 14 Gore-Tex», «Novablast 5 ATC Dame Grå/Sølv»);
# her får alle samme rene form.
_CAMEL = {"metaspeed": "MetaSpeed", "fujispeed": "FujiSpeed",
          "fujisetsu": "FujiSetsu", "metafuji": "MetaFuji"}
_UPPER = {"gt", "gtx", "atc", "tr", "mt", "ps", "ff", "wmns", "atr"}  # tokens som forblir versaler


def _cap_token(t: str) -> str:
    lw = t.lower()
    if lw in _CAMEL:
        return _CAMEL[lw]
    if lw in _UPPER:
        return t.upper()
    if any(c.isdigit() for c in t):
        return t.upper()                      # tall/spec ("2000", "14") — uendret
    return (t[:1].upper() + t[1:].lower()) if t else t


def _strip_lead_display(s: str) -> str:
    """Samme ledende-token-strip som match-nøkkelen, men case-bevarende, så
    visningsnavnet blir «Pegasus 42» av «Nike Air Zoom Pegasus 42»."""
    words = s.split()
    lowered = _strip_lead_tokens([w.lower() for w in words])
    return " ".join(words[len(words) - len(lowered):]) if lowered else s


_LEAD_GENDER = {"m": "herre", "w": "dame", "u": "unisex",
                "wmns": "dame", "mens": "herre", "womens": "dame"}


def split_model_gender(model: str) -> tuple[str, str | None]:
    """Trekk ut kjønnsord som har lekket inn i modellnavnet og kutt der.
    «Novablast 5 ATC Dame Grå/Sølv» -> ('Novablast 5 ATC', 'dame').
    Håndterer også LEDENDE kjønnsbokstaver (Hoka/Nike/Saucony-stil):
    «M Mach 6» -> ('Mach 6', 'herre'), «WMNS Air Winflo 11» -> (…, 'dame')."""
    s = (model or "").strip()
    lead_gender = None
    m = re.match(r"^(M|W|U|WMNS|Mens|Womens)\b[\s-]*", s, re.I)
    if m:
        lead_gender = _LEAD_GENDER.get(m.group(1).lower())
        s = s[m.end():].strip()
    m = re.search(r"\b(Herre|Dame|Barn|Unisex)\b", s, re.I)
    if m:
        return s[:m.start()].strip(), m.group(1).lower()
    return s, lead_gender


def _clean_tail_display(s: str) -> str:
    """Samme hale-rens som match-nøkkelen, men case-bevarende: kutter Men's/
    Women's-beskrivelser og trailing støy-/kjønnstokens fra visningsnavnet."""
    words = [w for w in s.replace(",", " ").split() if w]
    cleaned = _clean_tail_tokens([w.lower() for w in words])
    return " ".join(words[:len(cleaned)]) if cleaned else s


def canonical_model(model: str) -> str:
    """Pent visningsnavn: kjønn/farge/merke-/markedsføringsprefiks og
    beskrivelses-haler strippet, Gore-Tex/G-TX -> GTX, riktig casing."""
    cleaned, _ = split_model_gender(model)
    cleaned = re.sub(r"[\"'«»„“”|]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _strip_lead_display(cleaned)
    cleaned = _clean_tail_display(cleaned)
    s = re.sub(r"\bgore[\s-]?tex\b", "GTX", cleaned, flags=re.I)
    s = re.sub(r"\bg-tx\b", "GTX", s, flags=re.I)
    for sp, joined in _COMPOUNDS:                       # "Fuji Speed" -> "FujiSpeed"
        s = re.sub(re.escape(sp), joined, s, flags=re.I)
    return " ".join("-".join(_cap_token(p) for p in w.split("-")) for w in s.split())


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
