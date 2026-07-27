"""
prislop_cards.py — generator for Prisløps sosiale-medier-kort.

Tre korttyper, alle 1200x1200 (Facebook/Instagram feed), i sidens eget
designsystem (petrol/honey/paper + Space Grotesk). Ingen produktbilder fra
butikker eller merkevarer — kun egne data og egen grafikk, så ingen
opphavsrettsproblemer.

    1. price_drop_card()      — ekte prishistorikk-kurve som hovedvisual.
                                Brukes når historien er "prisen HAR falt".
    2. spread_card()          — søylediagram, billigste butikk i honey.
                                Brukes når historien er "samme sko, stor
                                forskjell mellom butikker" (drop14 er blind
                                for sko som selges billig fra dag én).
    3. spread_card_2panel()   — to søylediagrammer i ett kort (f.eks. dame
                                øverst, herre under) når kjønnene har ulik
                                prisspredning.

AVHENGIGHETER
    pip install -r marketing/requirements.txt
    Fontene Space Grotesk (Bold + Medium) må ligge i FONT_DIR. Hentes fra:
    https://github.com/floriankarsten/space-grotesk/tree/master/fonts/ttf/static
    Sett katalogen med PRISLOP_FONT_DIR (default: gjeldende katalog).

DESIGNPRINSIPPER (lært den harde veien)
    * All layout måles med font-metrikk og stables — aldri prosent-gjetning.
      Første versjon av kortene hadde tekst som kolliderte og rant utenfor.
    * Ikonet fra nettsiden (SHOE_SVG) tåler IKKE oppskalering til 500px. Bruk
      data som visual i stedet — det er mer "on brand" uansett.
    * QA-funksjonen nederst sjekker at ingenting kutter kanten og at blokkene
      ikke overlapper. Kjør den før du poster.

DATAREGLER FØR DU LAGER ET KORT (se også CLAUDE.md / Notion-briefen)
    * Verifiser alltid mot v_prislop_price_series, ikke drop14/deal_gap alene.
    * sizes_in_stock er summert på tvers av fargevarianter — tell distinkte
      størrelser i stedet.
    * Sjekk lagerdybden hos den BILLIGSTE butikken, ikke på tvers av alle.
    * Sjekk om lavprisen er medlemspris (Sport 1, Bull B+) — merk det i så fall
      i eyebrow-teksten.
"""

import os
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- designsystem
PAPER = (243, 245, 243)   # --paper
INK = (22, 33, 31)        # --ink
PETROL = (19, 110, 104)   # --petrol
PETROL_SOFT = (225, 237, 235)
HONEY = (188, 122, 30)    # --honey
MUTED = (94, 107, 102)
LINE = (225, 230, 226)

FONT_DIR = os.environ.get("PRISLOP_FONT_DIR", ".")
BOLD = os.path.join(FONT_DIR, "SpaceGrotesk-Bold.ttf")
MED = os.path.join(FONT_DIR, "SpaceGrotesk-Medium.ttf")

SS = 3                    # supersampling — rendres 3x, nedskaleres til slutt
OUT = 1200                # endelig kantlengde i px

# prislinje-merket fra index.html (viewBox 0 0 28 20)
LOGO = [(1, 4), (7, 9), (13, 5.5), (19, 12.5), (24.5, 17)]


# ------------------------------------------------------------------ hjelpere
def nok(n):
    """1560 -> '1 560' (norsk tusenskille)."""
    return f"{n:,.0f}".replace(",", "\u00a0").replace("\u00a0", " ")


def _th(d, txt, f):
    """Ekte høyde + top-offset for en tekst. Grunnlaget for all stabling."""
    b = d.textbbox((0, 0), txt, font=f)
    return b[3] - b[1], b[1]


def _center(d, txt, f, y, fill, W):
    """Sentrer tekst horisontalt med y som TOPP av glyfene. Returnerer høyden."""
    w = d.textlength(txt, font=f)
    h, off = _th(d, txt, f)
    d.text(((W - w) / 2, y - off), txt, font=f, fill=fill)
    return h


def _draw_mark(d, x, y, unit):
    """Prislinje-merket (samme geometri som logoen på nettsiden)."""
    s = unit / 28.0
    pts = [((px * s) + x, (py * s) + y) for px, py in LOGO]
    lw = max(2, int(unit * (2.3 / 28)))
    d.line(pts, fill=PETROL, width=lw, joint="curve")
    r = lw / 2
    for px, py in (pts[0], pts[-1]):
        d.ellipse([px - r, py - r, px + r, py + r], fill=PETROL)
    dr = 3 * s
    ex, ey = pts[-1]
    d.ellipse([ex - dr, ey - dr, ex + dr, ey + dr], fill=HONEY)


def _header(d, W, pad, badge_text=None):
    """Logo + ordmerke øverst til venstre, valgfri honey-badge øverst til høyre."""
    _draw_mark(d, pad, pad * 0.72, W * 0.052)
    d.text((pad + W * 0.072, pad * 0.66), "Prisløp",
           font=ImageFont.truetype(BOLD, int(W * 0.034)), fill=INK)
    if badge_text is None:
        return
    f_badge = ImageFont.truetype(BOLD, int(W * 0.042))
    bw = d.textlength(badge_text, font=f_badge)
    bh, boff = _th(d, badge_text, f_badge)
    px_, py_ = int(W * 0.028), int(W * 0.018)
    bx1, by0 = W - pad, pad * 0.55
    bx0, by1 = bx1 - bw - 2 * px_, by0 + bh + 2 * py_
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(W * 0.016), fill=HONEY)
    d.text((bx0 + px_, by0 + py_ - boff), badge_text, font=f_badge, fill=PAPER)


def _wrap(d, text, font, max_w):
    """Brekk tekst over flere linjer så den holder seg innenfor max_w."""
    words, lines, cur = text.split(" "), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def _footer_block(d, W, y, eyebrow, brand, model, footer, big_line=None):
    """Nederste tekstblokk: eyebrow / merke / modell / (stor pris) / fotnote."""
    f_eye = ImageFont.truetype(MED, int(W * 0.028))
    f_brand = ImageFont.truetype(MED, int(W * 0.040))
    f_model = ImageFont.truetype(BOLD, int(W * 0.066))
    f_big = ImageFont.truetype(BOLD, int(W * 0.098))
    f_foot = ImageFont.truetype(MED, int(W * 0.027))

    gap_s, gap_m, gap_l = int(W * 0.012), int(W * 0.020), int(W * 0.028)
    y += _center(d, eyebrow, f_eye, y, MUTED, W) + gap_m
    y += _center(d, brand, f_brand, y, (60, 68, 64), W) + gap_s
    lines = _wrap(d, model, f_model, W * 0.86)
    h_model = _th(d, "X", f_model)[0]
    for i, ln in enumerate(lines):
        y += _center(d, ln, f_model, y, INK, W)
        if i < len(lines) - 1:
            y += int(h_model * 0.28)
    y += gap_m
    if big_line:
        y += _center(d, big_line, f_big, y, HONEY, W) + gap_l
    else:
        y += gap_l - gap_m
    _center(d, footer, f_foot, y, MUTED, W)


def _footer_height(d, W, model, with_big):
    """Mål bunnblokken FØR den tegnes, så grafen kan få resten av plassen."""
    f_eye = ImageFont.truetype(MED, int(W * 0.028))
    f_brand = ImageFont.truetype(MED, int(W * 0.040))
    f_model = ImageFont.truetype(BOLD, int(W * 0.066))
    f_big = ImageFont.truetype(BOLD, int(W * 0.098))
    f_foot = ImageFont.truetype(MED, int(W * 0.027))
    gap_s, gap_m, gap_l = int(W * 0.012), int(W * 0.020), int(W * 0.028)
    n_lines = len(_wrap(d, model, f_model, W * 0.86))
    h_model = _th(d, "X", f_model)[0]
    h = (_th(d, "X", f_eye)[0] + gap_m
         + _th(d, "X", f_brand)[0] + gap_s
         + n_lines * h_model + (n_lines - 1) * int(h_model * 0.28)
         + gap_m
         + ((_th(d, "X", f_big)[0] + gap_l) if with_big else (gap_l - gap_m))
         + _th(d, "X", f_foot)[0])
    return h


# ------------------------------------------------------- 1. prisfall-kortet
def price_drop_card(brand, model, series, pct_off, eyebrow, footer, out_path):
    """
    series: liste av (etikett, pris) i kronologisk rekkefølge — den EKTE
            serien fra v_prislop_price_series. Etiketten brukes ikke visuelt,
            men holder rekkefølgen lesbar i koden.
    pct_off: heltall, skal stemme med drop14 avrundet til hele prosent.
    """
    W = H = OUT * SS
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    pad = int(W * 0.072)

    _header(d, W, pad, f"−{pct_off} %")

    big = f"fra {nok(series[-1][1])} kr"
    block_h = _footer_height(d, W, model, with_big=True)
    y_block = H - int(H * 0.088) - block_h
    chart_bottom = y_block - int(H * 0.055)

    # kurven
    cx0, cx1 = pad, W - pad
    cy0, cy1 = int(H * 0.235), chart_bottom
    prices = [p for _, p in series]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1
    n = len(series)
    X = (lambda i: cx0 + (i / (n - 1)) * (cx1 - cx0)) if n > 1 else (lambda i: cx0)
    Y = lambda p: cy1 - ((p - lo) / span) * (cy1 - cy0)
    pts = [(X(i), Y(p)) for i, (_, p) in enumerate(series)]

    d.polygon(pts + [(cx1, cy1 + int(H * 0.02)), (cx0, cy1 + int(H * 0.02))],
              fill=PETROL_SOFT)
    d.line(pts, fill=PETROL, width=int(W * 0.011), joint="curve")

    # honey-markør på siste punkt + stiplet guide ned
    ex, ey = pts[-1]
    yy = int(ey)
    while yy < int(cy1 + H * 0.02):
        d.line([(ex, yy), (ex, min(yy + int(H * 0.013), int(cy1 + H * 0.02)))],
               fill=HONEY, width=int(W * 0.004))
        yy += int(H * 0.028)
    rr = int(W * 0.028)
    d.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], outline=HONEY, width=int(W * 0.007))
    dr = int(W * 0.013)
    d.ellipse([ex - dr, ey - dr, ex + dr, ey + dr], fill=HONEY)

    # "før"-etikett ved kurvens start
    f_tag = ImageFont.truetype(MED, int(W * 0.030))
    sx, sy = pts[0]
    tag = f"{nok(prices[0])} kr"
    tg_h, tg_off = _th(d, tag, f_tag)
    d.text((sx + int(W * 0.012), sy - tg_h - int(H * 0.022) - tg_off),
           tag, font=f_tag, fill=MUTED)
    d.line([(sx, sy - int(H * 0.016)), (sx, sy - int(H * 0.004))],
           fill=MUTED, width=int(W * 0.003))

    _footer_block(d, W, y_block, eyebrow, brand, model, footer, big_line=big)
    img.resize((OUT, OUT), Image.LANCZOS).save(out_path)
    return out_path


# --------------------------------------------------------- 2. spread-kortet
def _draw_bars(d, W, pad, cy_top, cy_bot, bars, f_store, f_price):
    """Søyler med pris over og butikknavn under. Billigste i honey."""
    maxp = max(p for _, p, _ in bars)
    n = len(bars)
    slot = (W - 2 * pad) / n
    barw = slot * 0.60
    price_h = _th(d, "0", f_price)[0]
    avail_h = (cy_bot - cy_top) - price_h - int(W * 0.014)

    for i, (store, price, is_low) in enumerate(bars):
        bh_ = avail_h * (price / maxp)
        bx = pad + i * slot + (slot - barw) / 2
        by = cy_bot - bh_
        d.rounded_rectangle([bx, by, bx + barw, cy_bot], radius=int(W * 0.008),
                            fill=HONEY if is_low else PETROL_SOFT)
        ptxt = nok(price)
        pw = d.textlength(ptxt, font=f_price)
        poff = _th(d, ptxt, f_price)[1]
        d.text((bx + (barw - pw) / 2, by - price_h - int(W * 0.010) - poff),
               ptxt, font=f_price, fill=HONEY if is_low else MUTED)
        sw = d.textlength(store, font=f_store)
        soff = _th(d, store, f_store)[1]
        d.text((pad + i * slot + (slot - sw) / 2, cy_bot + int(W * 0.012) - soff),
               store, font=f_store, fill=INK if is_low else MUTED)

    d.line([(pad, cy_bot), (W - pad, cy_bot)], fill=LINE, width=max(2, int(W * 0.002)))


def spread_card(brand, model, bars, pct_vs_common, eyebrow, footer, out_path):
    """
    bars: [(butikknavn, pris, er_billigst)] sortert fra billigst til dyrest.
          Bruk KORTE butikknavn ("Oslo Sportsl.", "Bull") så de får plass.
    pct_vs_common: gapet mot de andre butikkene, heltall.
    """
    W = H = OUT * SS
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    pad = int(W * 0.072)

    _header(d, W, pad, f"−{pct_vs_common} %")

    block_h = _footer_height(d, W, model, with_big=False)
    y_block = H - int(H * 0.088) - block_h

    f_store = ImageFont.truetype(MED, int(W * 0.026))
    f_price = ImageFont.truetype(BOLD, int(W * 0.030))
    store_h = _th(d, "X", f_store)[0]
    cy_top = int(H * 0.235)
    cy_bot = y_block - int(H * 0.050) - store_h

    _draw_bars(d, W, pad, cy_top, cy_bot, bars, f_store, f_price)
    _footer_block(d, W, y_block, eyebrow, brand, model, footer)
    img.resize((OUT, OUT), Image.LANCZOS).save(out_path)
    return out_path


# ------------------------------------------------ 3. to-panels spread-kortet
def _panel(d, W, pad, y_top, y_bot, label, bars, gap_pct):
    f_label = ImageFont.truetype(BOLD, int(W * 0.030))
    f_gap = ImageFont.truetype(MED, int(W * 0.026))
    f_store = ImageFont.truetype(MED, int(W * 0.024))
    f_price = ImageFont.truetype(BOLD, int(W * 0.028))

    lh, loff = _th(d, label, f_label)
    d.text((pad, y_top - loff), label, font=f_label, fill=INK)
    if gap_pct is not None:
        gtxt = f"−{gap_pct} % hos billigste"
        gw = d.textlength(gtxt, font=f_gap)
        goff = _th(d, gtxt, f_gap)[1]
        d.text((W - pad - gw, y_top - goff + int(lh * 0.12)), gtxt, font=f_gap, fill=HONEY)

    cy_top = y_top + lh + int(W * 0.030)
    store_h = _th(d, "X", f_store)[0]
    cy_bot = y_bot - store_h - int(W * 0.016)
    _draw_bars(d, W, pad, cy_top, cy_bot, bars, f_store, f_price)


def spread_card_2panel(brand, model, panel_a, panel_b, eyebrow, footer, out_path):
    """
    panel_a / panel_b: (label, bars, gap_pct) — gap_pct=None dropper gap-teksten
    (bruk det når spennet i panelet er lite, så kortet ikke overselger).
    """
    W = H = OUT * SS
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    pad = int(W * 0.072)

    _header(d, W, pad)  # ingen global badge — hvert panel har sin egen

    block_h = _footer_height(d, W, model, with_big=False)
    y_block = H - int(H * 0.070) - block_h

    panels_top = int(H * 0.145)
    panels_bot = y_block - int(H * 0.040)
    panel_gap = int(H * 0.055)
    ph = (panels_bot - panels_top - panel_gap) / 2

    _panel(d, W, pad, panels_top, panels_top + ph, *panel_a)
    _panel(d, W, pad, panels_top + ph + panel_gap, panels_bot, *panel_b)

    _footer_block(d, W, y_block, eyebrow, brand, model, footer)
    img.resize((OUT, OUT), Image.LANCZOS).save(out_path)
    return out_path


# ------------------------------------------------------------------ QA-sjekk
def qa(path, verbose=True):
    """
    Numerisk kvalitetskontroll — kjør ALLTID før du poster.
    Sjekker at ingenting kutter kanten og at tekstblokkene ikke overlapper.
    """
    import numpy as np
    a = np.array(Image.open(path).convert("RGB"))
    H, W, _ = a.shape
    P = np.array(PAPER)
    ring = np.concatenate([a[:12].reshape(-1, 3), a[-12:].reshape(-1, 3),
                           a[:, :12].reshape(-1, 3), a[:, -12:].reshape(-1, 3)])
    edge = int(np.abs(ring.astype(int) - P).sum(1).max())
    rows = (np.abs(a.astype(int) - P).sum(2).sum(1) > 2000)
    runs, s = [], None
    for i, v in enumerate(rows):
        if v and s is None:
            s = i
        if not v and s is not None:
            runs.append((s, i)); s = None
    if s is not None:
        runs.append((s, H))
    res = {"edge_clean": edge == 0, "top_margin": runs[0][0] if runs else None,
           "bottom_margin": H - runs[-1][1] if runs else None, "bands": len(runs)}
    if verbose:
        print(f"{path}: kant {'OK' if edge == 0 else f'KUTTER ({edge})'} | "
              f"topmarg {res['top_margin']} | bunnmarg {res['bottom_margin']} | "
              f"{res['bands']} innholdsbånd")
    return res


# ---------------------------------------------------------------- eksempler
if __name__ == "__main__":
    # 1. prisfall — Saucony Endorphin Speed 5 (ekte serie, 14. juli)
    price_drop_card(
        brand="Saucony", model="Endorphin Speed 5",
        series=[("07-05", 2499), ("07-06", 2499), ("07-07", 2499), ("07-08", 2499),
                ("07-09", 2499), ("07-10", 1500), ("07-11", 1500), ("07-12", 1500),
                ("07-13", 1500), ("07-14", 1500)],
        pct_off=40,
        eyebrow="PRISFALL · TEMPO & SUPERTRAINER",
        footer="Laveste pris hos 5 norske butikker · prisløp.no",
        out_path="kort-prisfall-eksempel.png")
    qa("kort-prisfall-eksempel.png")

    # 2. spread — Hoka Skyward X (ekte priser, 18. juli)
    spread_card(
        brand="Hoka", model="Skyward X",
        bars=[("Bull", 1979, True), ("Oslo Sportsl.", 2145, False),
              ("Sport 1", 3299, False), ("Löplabbet", 3300, False)],
        pct_vs_common=40,
        eyebrow="FORRIGE MODELL · 4 BUTIKKER",
        footer="Billigst hos Bull Ski & Kajakk · prisløp.no",
        out_path="kort-spread-eksempel.png")
    qa("kort-spread-eksempel.png")

    # 3. to paneler — Hoka Bondi 9, ulik spredning dame/herre
    spread_card_2panel(
        brand="Hoka", model="Bondi 9",
        panel_a=("DAME", [("Oslo Sportsl.", 1559, True), ("Bull", 1919, False),
                          ("Sport 1", 2299, False)], 26),
        panel_b=("HERRE", [("Oslo Sportsl.", 1559, True), ("Sport 1", 1599, False),
                           ("Bull", 1679, False)], None),
        eyebrow="SAMME SKO · 3 BUTIKKER",
        footer="Billigst hos Oslo Sportslager · prisløp.no",
        out_path="kort-2panel-eksempel.png")
    qa("kort-2panel-eksempel.png")
