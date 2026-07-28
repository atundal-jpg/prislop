"""
Engangsskript: spread-kort for Nike Structure 26 dame (data verifisert 28. juli).

Kjør fra marketing/:
    PRISLOP_FONT_DIR=fonts python3 kort_nike_structure_26_dame.py

Tall (v_prislop_price_series / v_prislop_offers / v_prislop_sizes, 28. juli):
    XXL 799 (billigst) · Torshov Sport 1 119 · Intersport 1 699
    7 distinkte størrelser hos XXL (svart) — IKKE sizes_in_stock, som er
    summert på tvers av fargevarianter.
    Historikk: 1 119 fra 5.–21. juli, falt til 799 den 22. juli (7 dager).
    Butikktelling stabil på 3 gjennom hele perioden.
"""

from PIL import Image, ImageDraw, ImageFont

from prislop_cards import BOLD, MED, OUT, SS, _th, _wrap, spread_card, qa

BRAND = "Nike"
MODEL = "Structure 26"
BARS = [("XXL", 799, True),
        ("Torshov Sport", 1119, False),
        ("Intersport", 1699, False)]
# Badge: gapet ned til NESTE butikk (1 119 -> 799 = 28,6 %). Bevisst det
# konservative tallet — mot dyreste butikk ville det blitt 53 %.
PCT = 29
EYEBROW = "DAME · 3 BUTIKKER · PRISFALL 22. JULI"
FOOTER = "7 størrelser på lager hos XXL · prisløp.no"
OUT_PATH = "kort-nike-structure-26-dame.png"


def fit_check():
    """Måler tekstbredder mot malens egne grenser FØR rendering."""
    W = OUT * SS
    pad = int(W * 0.072)
    d = ImageDraw.Draw(Image.new("RGB", (W, W)))
    ok = True

    def line(name, txt, font, limit):
        nonlocal ok
        w = d.textlength(txt, font=font)
        slack = limit - w
        ok &= slack >= 0
        print(f"  {name:<24} {w/SS:7.1f}px av {limit/SS:7.1f}px "
              f"-> slack {slack/SS:7.1f}px {'OK' if slack >= 0 else 'FOR BRED'}")

    print("tekstbredder (px i endelig 1200-skala):")
    line("eyebrow", EYEBROW, ImageFont.truetype(MED, int(W * 0.028)), W - 2 * pad)
    line("footer", FOOTER, ImageFont.truetype(MED, int(W * 0.027)), W - 2 * pad)
    line("brand", BRAND, ImageFont.truetype(MED, int(W * 0.040)), W - 2 * pad)
    for ln in _wrap(d, MODEL, ImageFont.truetype(BOLD, int(W * 0.066)), W * 0.86):
        line(f"modell «{ln}»", ln, ImageFont.truetype(BOLD, int(W * 0.066)), W * 0.86)

    # butikknavn + priser: hver etikett må holde seg i sin egen kolonne
    f_store = ImageFont.truetype(MED, int(W * 0.026))
    f_price = ImageFont.truetype(BOLD, int(W * 0.030))
    slot = (W - 2 * pad) / len(BARS)
    print(f"\nsøylekolonner (slot {slot/SS:.1f}px):")
    edges = []
    for i, (store, price, _) in enumerate(BARS):
        sw = d.textlength(store, font=f_store)
        pw = d.textlength(f"{price:,}".replace(",", " "), font=f_price)
        cx = pad + i * slot + slot / 2
        edges.append((cx - sw / 2, cx + sw / 2))
        for nm, w_ in (("butikk", sw), ("pris", pw)):
            slack = slot - w_
            ok &= slack >= 0
            print(f"  {store:<15} {nm:<7} {w_/SS:6.1f}px -> slack {slack/SS:6.1f}px "
                  f"{'OK' if slack >= 0 else 'FOR BRED'}")
    print("\nklaring mellom butikknavn:")
    for i in range(len(edges) - 1):
        gap = edges[i + 1][0] - edges[i][1]
        ok &= gap > 0
        print(f"  {BARS[i][0]} | {BARS[i+1][0]}: {gap/SS:.1f}px "
              f"{'OK' if gap > 0 else 'KOLLIDERER'}")
    left = edges[0][0] - pad
    right = (W - pad) - edges[-1][1]
    ok &= left >= 0 and right >= 0
    print(f"  venstre marg {left/SS:.1f}px | høyre marg {right/SS:.1f}px "
          f"{'OK' if left >= 0 and right >= 0 else 'UTENFOR'}")
    print(f"\nfit_check: {'ALLE OK' if ok else 'FEIL'}")
    return ok


if __name__ == "__main__":
    fit_check()
    print()
    spread_card(brand=BRAND, model=MODEL, bars=BARS, pct_vs_common=PCT,
                eyebrow=EYEBROW, footer=FOOTER, out_path=OUT_PATH)
    qa(OUT_PATH)
