"""Build a single-file HTML report for one bench input.

Usage:
    python report.py <bench_dir> <input_name> <outputs_dir> [--notes notes.json] [--out report.html]

Reads <bench_dir>/bench.yaml, <outputs_dir>/<input>_scores.json and the output images
(<outputs_dir>/<input>__<recipe>__s<seed>.png). Everything is embedded, so the HTML can be
shared as one file.
"""
import argparse
import base64
import html
import io
import json
import os
import re
from datetime import date

import cv2
import numpy as np
import yaml
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab

L_RANGE = (12, 95)
HEAT_MAX = 10.0  # ΔE at which the heatmap saturates

# Gates: (group, key, label, plain-language question, test, unit)
GATES = [
    ("Geometry", "aspect_err", "Aspect", "Same proportions as the original?", lambda v: v <= 0.02, "", 3),
    ("Geometry", "shift_px", "Shift", "Product stayed in place (≤ 1 px)?", lambda v: v <= 1.0, "px", 1),
    ("Geometry", "mask_iou", "Outline", "Product outline overlaps the original (IoU ≥ 0.98)?", lambda v: v >= 0.98, "IoU", 3),
    ("Colour", "dE_prod_mean", "Colour", "Product colour kept (mean ΔE ≤ 3, lightness ignored)?", lambda v: v <= 3.0, "ΔE", 2),
    ("Colour", "dE_prod_p95", "Colour p95", "No patch drifted far (p95 ΔE ≤ 6)?", lambda v: v <= 6.0, "ΔE", 2),
    ("Backdrop", "dE_bg_mean", "Backdrop hue", "Backdrop colour kept (ΔE ≤ 3)?", lambda v: v <= 3.0, "ΔE", 2),
    ("Backdrop", "bg_L_shift", "Backdrop light", "Backdrop brightness kept (|ΔL*| ≤ 10)?", lambda v: abs(v) <= 10.0, "L*", 1),
    ("Relight", "lr_shift_L", "Key light", "More light from the left (≥ +3 L*)?", lambda v: v >= 3.0, "L*", 1),
    ("Relight", "contrast_ratio", "Contrast", "Harder light (shading contrast ≥ 1.15×)?", lambda v: v >= 1.15, "×", 2),
    ("Logo", "ssim_logo_norm", "Logo", "Logo structure kept (SSIM ≥ 0.85)?", lambda v: v >= 0.85, "SSIM", 2),
]

INFO = [
    ("ssim_prod_norm", "Product structure", "Luminance-normalised SSIM inside the product. Relighting changes "
     "shading by design, so this is shown for reference and not used as a gate until calibrated.", "SSIM"),
    ("sharpness_rel", "Sharpness", "Laplacian variance inside the product, relative to the original (1.0 = same).", "×"),
    ("scale", "Scale", "Product area relative to the original (1.0 = same size).", "×"),
    ("out_size", "Native size", "Pixel size the model returned, before resampling to the original size.", "px"),
]


# ---------- image helpers ----------

def load_rgb(path, size=None):
    im = Image.open(path).convert("RGB")
    if size and im.size != size:
        im = im.resize(size, Image.BICUBIC)
    return np.asarray(im).astype(np.float64) / 255.0


def load_mask(path, size):
    im = Image.open(path)
    a = im.split()[-1] if im.mode in ("RGBA", "LA") else im.convert("L")
    if a.size != size:
        a = a.resize(size, Image.BILINEAR)
    return np.asarray(a) > 127


def erode(mask, pct=0.15):
    k = max(1, int(round(max(mask.shape) * pct / 100)))
    return cv2.erode(mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0


def to_data_uri(arr_or_img, width=None, quality=84):
    img = arr_or_img if isinstance(arr_or_img, Image.Image) else Image.fromarray(
        (np.clip(arr_or_img, 0, 1) * 255).astype(np.uint8))
    if width and img.width != width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


RAMP = np.array([[0xcd, 0xe2, 0xfb], [0x86, 0xb6, 0xef], [0x2a, 0x78, 0xd6], [0x1c, 0x5c, 0xab], [0x0d, 0x36, 0x6b]]) / 255.0


def ramp(t):
    t = np.clip(t, 0, 1) * (len(RAMP) - 1)
    i = np.minimum(np.floor(t).astype(int), len(RAMP) - 2)
    f = (t - i)[..., None]
    return RAMP[i] * (1 - f) + RAMP[i + 1] * f


def heatmap(rgb_in, rgb_out, m_in, m_out):
    """Hue/chroma ΔE inside the product, on a faded greyscale of the output."""
    lab_in, lab_out = rgb2lab(rgb_in), rgb2lab(rgb_out)
    both = erode(m_in & m_out)
    mid = (lab_in[..., 0] > L_RANGE[0]) & (lab_in[..., 0] < L_RANGE[1]) & \
          (lab_out[..., 0] > L_RANGE[0]) & (lab_out[..., 0] < L_RANGE[1])
    sel = both & mid
    b = lab_out.copy()
    b[..., 0] = lab_in[..., 0]
    de = deltaE_ciede2000(lab_in, b)
    grey = rgb_out.mean(axis=2, keepdims=True)
    out = 0.82 + 0.18 * np.repeat(grey, 3, axis=2)  # faded context
    out[sel] = ramp(de[sel] / HEAT_MAX)
    return out


# ---------- data ----------

def listed_price(notes):
    m = re.search(r"\$\s?(\d+(?:\.\d+)?)", notes or "")
    return float(m.group(1)) if m else None


def evaluate(row):
    results = []
    for group, key, label, question, test, unit, digits in GATES:
        v = row.get(key)
        ok = None if v is None else bool(test(v))
        results.append({"group": group, "key": key, "label": label, "question": question,
                        "value": v, "ok": ok, "unit": unit, "digits": digits})
    return results


def fmt(v, digits=None):
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and digits is not None:
        return f"{v:.{digits}f}"
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"
    return str(v)


# ---------- SVG scatter ----------

def scatter_svg(rows):
    W, H, ml, mr, mt, mb = 1100, 440, 64, 24, 20, 52
    xs = [r["contrast_ratio"] for r in rows]
    ys = [r["dE_prod_mean"] for r in rows]
    x0, x1 = min(0.8, min(xs) - 0.1), max(xs) + 0.25
    y0, y1 = 0, max(4.0, max(ys) + 0.5)
    sx = lambda v: ml + (v - x0) / (x1 - x0) * (W - ml - mr)
    sy = lambda v: mt + (1 - (v - y0) / (y1 - y0)) * (H - mt - mb)
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-labelledby="sc-title sc-desc">',
         '<title id="sc-title">Relight strength against colour drift</title>',
         '<desc id="sc-desc">Each dot is one recipe. Right means harder light, down means less colour drift. '
         'The shaded corner is where a recipe both relights and keeps the product colour.</desc>']
    # target zone
    p.append(f'<rect x="{sx(1.15):.1f}" y="{sy(3):.1f}" width="{W - mr - sx(1.15):.1f}" '
             f'height="{sy(y0) - sy(3):.1f}" class="zone"/>')
    # grid + axes
    for t in np.arange(0, y1 + 0.01, 1):
        p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="grid"/>'
                 f'<text x="{ml - 8}" y="{sy(t) + 4:.1f}" class="tick" text-anchor="end">{t:.0f}</text>')
    for t in np.arange(np.ceil(x0 * 4) / 4, x1 + 0.01, 0.25):
        if abs(t * 2 - round(t * 2)) < 1e-6:
            p.append(f'<text x="{sx(t):.1f}" y="{H - mb + 18}" class="tick" text-anchor="middle">{t:.1f}×</text>')
    p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(y0):.1f}" y2="{sy(y0):.1f}" class="axis"/>')
    p.append(f'<line x1="{sx(1.15):.1f}" x2="{sx(1.15):.1f}" y1="{mt}" y2="{sy(y0):.1f}" class="gate"/>')
    p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(3):.1f}" y2="{sy(3):.1f}" class="gate"/>')
    p.append(f'<text x="{W - mr - 6}" y="{sy(y0) - 8:.1f}" class="zone-label" text-anchor="end">'
             'Relit and faithful</text>')
    p.append(f'<text x="{ml + 6}" y="{sy(y0) - 8:.1f}" class="zone-label muted">Faithful, but barely relit</text>')
    p.append(f'<text x="{(ml + W - mr) / 2:.1f}" y="{H - 8}" class="axis-title" text-anchor="middle">'
             'Shading contrast vs original → harder light</text>')
    p.append(f'<text transform="translate(14 {(mt + sy(y0)) / 2:.1f}) rotate(-90)" class="axis-title" '
             'text-anchor="middle">Product colour drift (mean ΔE) ↓ better</text>')
    # points + labels, greedy placement to avoid overlaps
    placed = []
    pts = sorted(rows, key=lambda r: r["dE_prod_mean"])
    for r in pts:
        cx, cy = sx(r["contrast_ratio"]), sy(r["dE_prod_mean"])
        placed.append((cx - 6, cy - 6, cx + 6, cy + 6))
    for r in pts:
        cx, cy = sx(r["contrast_ratio"]), sy(r["dE_prod_mean"])
        name = r["recipe"]
        w = 6.6 * len(name)
        for dx, dy, anchor in [(10, 4, "start"), (-10, 4, "end"), (10, -10, "start"), (10, 18, "start"),
                               (-10, -10, "end"), (-10, 18, "end")]:
            bx0 = cx + dx if anchor == "start" else cx + dx - w
            box = (bx0, cy + dy - 11, bx0 + w, cy + dy + 3)
            inside = box[0] >= ml and box[2] <= W - mr and box[1] >= mt
            if inside and not any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3])
                                  for b in placed):
                placed.append(box)
                break
        tip = (f'{name} · contrast {r["contrast_ratio"]:.2f}× · ΔE {r["dE_prod_mean"]:.2f} · '
               f'{r["_fails"]} gate(s) failed')
        p.append(f'<g class="pt" data-tip="{html.escape(tip)}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" '
                 f'class="hit"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot"/>'
                 f'<text x="{cx + dx:.1f}" y="{cy + dy:.1f}" text-anchor="{anchor}" class="lbl">'
                 f'{html.escape(name)}</text></g>')
    p.append("</svg>")
    return "\n".join(p)


# ---------- HTML ----------

CSS = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--card:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--accent:#2a78d6;--good:#0ca30c;--good-ink:#006300;--crit:#d03b3b;
--crit-ink:#a32626;--warn:#fab219;--zone:rgba(12,163,12,.07);--chip-good:rgba(12,163,12,.10);
--chip-bad:rgba(208,59,59,.10);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--page:#0d0d0d;--surface:#1a1a19;
--card:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--accent:#3987e5;
--good-ink:#0ca30c;--crit-ink:#e66767;--zone:rgba(12,163,12,.12);--chip-good:rgba(12,163,12,.18);
--chip-bad:rgba(208,59,59,.20);color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 16px 72px;display:grid;gap:44px}
h1,h2,h3{margin:0;text-wrap:balance;letter-spacing:-.01em}h1{font-size:clamp(26px,4vw,36px)}
h2{font-size:22px}h3{font-size:15px}p{margin:0;max-width:72ch}
.muted{color:var(--muted)}.ink2{color:var(--ink2)}
.mono{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
section,header,.wrap>*,.split>*,.side,.panel{min-width:0}section{display:grid;gap:16px}
.meta{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--ink2);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--grid);border-radius:10px;padding:16px;display:grid;gap:4px}
.card .big{font-size:28px;font-weight:650}.card .lab{font-size:13px;color:var(--ink2)}
.notes{display:grid;gap:10px;margin:0;padding:0;list-style:none}
.notes li{background:var(--card);border:1px solid var(--grid);border-left:3px solid var(--accent);
border-radius:0 8px 8px 0;padding:12px 14px}.notes li.warn{border-left-color:var(--warn)}
.tablewrap{overflow-x:auto;border:1px solid var(--grid);border-radius:10px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 6px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:middle;white-space:nowrap}
tr:last-child td{border-bottom:0}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
th.grp{text-align:center;border-bottom:0;padding-bottom:0}
.chip{white-space:nowrap;flex-shrink:0;display:inline-flex;align-items:center;gap:4px;border-radius:99px;padding:2px 7px;font-size:11.5px}
.chip.ok{background:var(--chip-good);color:var(--good-ink)}.chip.bad{background:var(--chip-bad);color:var(--crit-ink)}
.chip.na{color:var(--muted);border:1px dashed var(--axis)}
.rank{font-weight:650}.rowname{font-weight:600}
.chartwrap{overflow-x:auto;border-radius:10px}.chart{width:100%;min-width:960px;height:auto;background:var(--surface);border:1px solid var(--grid);border-radius:10px}
.chart .grid{stroke:var(--grid);stroke-width:1}.chart .axis{stroke:var(--axis);stroke-width:1}
.chart .gate{stroke:var(--good);stroke-width:1;stroke-dasharray:4 4;opacity:.7}
.chart .zone{fill:var(--zone)}.chart .zone-label{font-size:12px;fill:var(--good-ink)}
.chart .zone-label.muted{fill:var(--muted)}
.chart .tick{font-size:11px;fill:var(--muted)}.chart .axis-title{font-size:12px;fill:var(--ink2)}
.chart .dot{fill:var(--accent);stroke:var(--surface);stroke-width:2}.chart .hit{fill:transparent}
.chart .lbl{font-size:11.5px;fill:var(--ink2)}.chart .pt:hover .dot{r:7}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--page);font-size:12px;
padding:6px 9px;border-radius:6px;opacity:0;transition:opacity .1s;z-index:9;max-width:320px}
.split{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:860px){.split{grid-template-columns:1fr}}
.picker{display:flex;flex-wrap:wrap;gap:6px}
.picker button{font:inherit;font-size:13px;padding:6px 11px;border-radius:7px;border:1px solid var(--grid);
background:var(--card);color:var(--ink);cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.picker button[aria-pressed="true"]{border-color:var(--accent);box-shadow:inset 0 -2px 0 var(--accent)}
.picker button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.picker .n{font-size:11px;color:var(--muted)}
.ba{position:relative;border-radius:10px;overflow:hidden;border:1px solid var(--grid);background:#ddd;
user-select:none;touch-action:none}
.ba img{display:block;width:100%;height:auto}.ba .after{position:absolute;inset:0;clip-path:inset(0 0 0 50%)}
.ba .after img{height:100%;object-fit:cover}
.ba .bar{position:absolute;top:0;bottom:0;left:50%;width:2px;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.25)}
.ba .knob{position:absolute;top:50%;left:50%;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:grid;place-items:center;font-size:13px;color:#333}
.ba .tag{position:absolute;top:10px;font-size:12px;background:rgba(0,0,0,.6);color:#fff;padding:3px 8px;border-radius:5px}
.ba .tag.l{left:10px}.ba .tag.r{right:10px}
.side{display:grid;gap:14px}
.panel{background:var(--card);border:1px solid var(--grid);border-radius:10px;padding:14px;display:grid;gap:10px}
.panel img{width:100%;height:auto;border-radius:6px;display:block}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}.pair figure{margin:0;display:grid;gap:4px}
figcaption{font-size:12px;color:var(--muted)}
.legend-bar{height:10px;border-radius:5px;background:linear-gradient(90deg,#cde2fb,#86b6ef,#2a78d6,#1c5cab,#0d366b)}
.legend-ticks{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
dl.kv{display:grid;grid-template-columns:auto 1fr auto;gap:6px 10px;margin:0;font-size:13px;align-items:center}
dl.kv dt{color:var(--ink2)}dl.kv dd{margin:0;white-space:nowrap}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.gallery figure{margin:0;background:var(--card);border:1px solid var(--grid);border-radius:10px;overflow:hidden;
display:grid;cursor:pointer}.gallery figure:hover{border-color:var(--accent)}
.gallery img{width:100%;height:auto;display:block}.gallery figcaption{padding:8px 10px;display:flex;
justify-content:space-between;gap:6px;align-items:center;color:var(--ink)}
details{background:var(--card);border:1px solid var(--grid);border-radius:10px;padding:12px 14px}
summary{cursor:pointer;font-weight:600}
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const tip = document.querySelector('.tip');
document.querySelectorAll('.pt').forEach(g => {
  g.addEventListener('mousemove', e => { tip.textContent = g.dataset.tip; tip.style.opacity = 1;
    tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
  g.addEventListener('mouseleave', () => tip.style.opacity = 0);
});
const ba = document.querySelector('.ba'), after = ba.querySelector('.after'), bar = ba.querySelector('.bar'),
      knob = ba.querySelector('.knob');
function setPos(p){ p = Math.max(0, Math.min(1, p)); after.style.clipPath = `inset(0 0 0 ${p*100}%)`;
  bar.style.left = knob.style.left = (p*100) + '%'; }
let drag = false;
const move = e => { const r = ba.getBoundingClientRect(); setPos((e.clientX - r.left) / r.width); };
ba.addEventListener('pointerdown', e => { drag = true; ba.setPointerCapture(e.pointerId); move(e); });
ba.addEventListener('pointermove', e => drag && move(e));
ba.addEventListener('pointerup', () => drag = false);
ba.tabIndex = 0; let pos = .5;
ba.addEventListener('keydown', e => { if (e.key === 'ArrowLeft') setPos(pos -= .05); if (e.key === 'ArrowRight') setPos(pos += .05); });
function show(id){
  const r = D.recipes.find(x => x.recipe === id);
  ba.querySelector('.after img').src = r.img; ba.querySelector('.tag.r').textContent = id;
  document.getElementById('heat').src = r.heat; document.getElementById('logo-out').src = r.logo;
  document.getElementById('logo-out-cap').textContent = id;
  document.getElementById('kv').innerHTML = r.gates.map(g =>
    `<dt>${g.question}</dt><dd class="mono">${g.value_fmt}</dd><dd>${g.ok === null ? '<span class="chip na">n/a</span>'
     : g.ok ? '<span class="chip ok">✓ pass</span>' : '<span class="chip bad">✕ fail</span>'}</dd>`).join('');
  document.querySelectorAll('.picker button').forEach(b => b.setAttribute('aria-pressed', b.dataset.id === id));
}
document.querySelectorAll('[data-id]').forEach(el => el.addEventListener('click', () => {
  show(el.dataset.id); if (el.tagName === 'FIGURE') document.getElementById('compare').scrollIntoView({behavior:'smooth'}); }));
show(D.recipes[0].recipe);
"""


def build(bench_dir, inp, out_dir, notes_path=None, out_path=None):
    bench = yaml.safe_load(open(os.path.join(bench_dir, "bench.yaml"), encoding="utf8"))
    scores = json.load(open(os.path.join(out_dir, f"{inp}_scores.json"), encoding="utf8"))
    notes = json.load(open(notes_path, encoding="utf8")) if notes_path else {}
    item = next(i for i in bench["inputs"] if os.path.splitext(os.path.basename(i["path"]))[0] == inp)
    src = os.path.join(bench_dir, item["path"])
    W, H = Image.open(src).size
    rgb_in = load_rgb(src)
    m_in = load_mask(os.path.join(bench_dir, item["regions"]["product"]), (W, H))
    logo_box = item["regions"].get("logo", {}).get("box")
    recipes = {r["id"]: r for r in bench["recipes"]}

    def crop_logo(rgb):
        x0, y0, x1, y1 = logo_box
        return to_data_uri(rgb[y0:y1, x0:x1], width=360, quality=90)

    rows = []
    for s in scores:
        rid = s["recipe"]
        f = os.path.join(out_dir, f"{inp}__{rid}__s1.png")
        rgb_out = load_rgb(f, (W, H))
        m_out = load_mask(os.path.join(out_dir, "masks", f"{rid}_cut.png"), (W, H))
        gates = evaluate(s)
        for g in gates:
            g["value_fmt"] = fmt(g["value"], g["digits"]) + ("" if g["value"] is None else f" {g['unit']}")
        meta = recipes.get(rid, {})
        rows.append({**s, "model": meta.get("model", "?"), "price": listed_price(meta.get("notes")),
                     "gates": gates, "_fails": sum(1 for g in gates if g["ok"] is False),
                     "img": to_data_uri(rgb_out, width=900),
                     "thumb": to_data_uri(rgb_out, width=360, quality=80),
                     "heat": to_data_uri(heatmap(rgb_in, rgb_out, m_in, m_out), width=520),
                     "logo": crop_logo(rgb_out) if logo_box else ""})
    rows.sort(key=lambda r: (r["_fails"], r["dE_prod_mean"]))
    missing = [rid for rid in recipes if rid not in {r["recipe"] for r in rows}]
    passing = [r for r in rows if r["_fails"] == 0]
    spend = sum(r["price"] or 0 for r in rows)

    e = html.escape
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Bench report · {e(inp)}</title><style>{CSS}</style></head><body><div class='wrap'>"]

    # header
    out.append("<header style='display:grid;gap:12px'>"
               f"<div class='muted mono' style='font-size:12px'>runware-eval · smoke round · {date.today()}</div>"
               f"<h1>Which recipe relights <span class='mono'>{e(inp)}</span> best?</h1>"
               f"<p class='ink2'>{e(bench['goal'].strip())}</p>"
               f"<div class='meta'><span>{len(rows)} recipes scored</span><span>1 input · seed 1</span>"
               f"<span>{len(GATES)} gates</span><span>Listed spend ≈ ${spend:.2f}</span></div></header>")

    # verdict cards
    best = rows[0]
    relit = [r for r in rows if all(g['ok'] for g in r['gates'] if g['group'] == 'Relight')] or rows
    faithful = min(relit, key=lambda r: r['dE_prod_mean'])
    out.append("<section aria-label='Summary'><div class='cards'>"
               f"<div class='card'><span class='lab'>Recipes passing every gate</span>"
               f"<span class='big'>{len(passing)} / {len(rows)}</span>"
               f"<span class='lab'>{'None yet: see the notes below' if not passing else ', '.join(r['recipe'] for r in passing)}</span></div>"
               f"<div class='card'><span class='lab'>Closest</span><span class='big' style='font-size:20px'>{e(best['recipe'])}</span>"
               f"<span class='lab'>fails {best['_fails']}: {', '.join(g['label'] for g in best['gates'] if g['ok'] is False) or '—'}</span></div>"
               f"<div class='card'><span class='lab'>Lowest colour drift, among recipes that relit</span>"
               f"<span class='big'>{faithful['dE_prod_mean']:.2f} ΔE</span>"
               f"<span class='lab'>{e(faithful['recipe'])}</span></div>"
               f"<div class='card'><span class='lab'>Hardest light</span>"
               f"<span class='big'>{max(r['contrast_ratio'] for r in rows):.2f}×</span>"
               f"<span class='lab'>{e(max(rows, key=lambda r: r['contrast_ratio'])['recipe'])}</span></div>"
               "</div></section>")

    # notes
    if notes.get("findings") or missing:
        out.append("<section><h2>What this run says</h2><ul class='notes'>")
        for n in notes.get("findings", []):
            out.append(f"<li>{n}</li>")
        for n in notes.get("caveats", []):
            out.append(f"<li class='warn'>{n}</li>")
        if missing:
            out.append(f"<li class='warn'><strong>Not in this report:</strong> {', '.join(e(m) for m in missing)} "
                       "(no output or score found).</li>")
        out.append("</ul></section>")

    # trade-off chart
    out.append("<section><h2>The trade-off</h2><p class='ink2'>Relighting must change the light without changing "
               "the product. Each dot is one recipe; the shaded corner is where both hold. Hover a dot for values.</p>"
               + "<div class='chartwrap'>" + scatter_svg(rows) + "</div></section>")

    # gate matrix
    groups = []
    for g in GATES:
        if not groups or groups[-1][0] != g[0]:
            groups.append([g[0], 0])
        groups[-1][1] += 1
    out.append("<section><h2>Gate by gate</h2><p class='ink2'>Ranked by number of failed gates, then by colour "
               "drift. Every gate must pass; thresholds come from <span class='mono'>bench.yaml</span> and are "
               "provisional until calibrated.</p><div class='tablewrap'><table><thead><tr><th></th><th></th>"
               + "".join(f"<th class='grp' colspan='{n}'>{e(gname)}</th>" for gname, n in groups)
               + "<th></th></tr><tr><th>#</th><th>Recipe</th>"
               + "".join(f"<th title='{e(g[3])}'>{e(g[2])}</th>" for g in GATES)
               + "<th>Listed $/image</th></tr></thead><tbody>")
    for i, r in enumerate(rows, 1):
        cells = "".join(
            f"<td><span class='chip {'ok' if g['ok'] else 'bad'}' title='{e(g['question'])}'>"
            f"{'✓' if g['ok'] else '✕'} <span class='mono'>{fmt(g['value'], g['digits'])}</span></span></td>"
            for g in r["gates"])
        price = f"${r['price']:.3f}" if r["price"] is not None else "—"
        out.append(f"<tr><td class='rank'>{i}</td><td><button class='linklike rowname' data-id='{e(r['recipe'])}' "
                   f"style='all:unset;cursor:pointer;font-weight:600'>{e(r['recipe'])}</button>"
                   f"<div class='muted mono' style='font-size:11px'>{e(r['model'])}</div></td>{cells}"
                   f"<td class='mono'>{price}</td></tr>")
    out.append("</tbody></table></div></section>")

    # comparison viewer
    out.append("<section id='compare'><h2>Compare with the original</h2><div class='picker' role='group' "
               "aria-label='Recipe'>"
               + "".join(f"<button data-id='{e(r['recipe'])}' aria-pressed='false'>{e(r['recipe'])}"
                         f"<span class='n'>{r['_fails']}✕</span></button>" for r in rows)
               + "</div><div class='split'><div style='display:grid;gap:6px'>"
               f"<div class='ba' aria-label='Drag to compare original and output'>"
               f"<img src='{to_data_uri(rgb_in, width=900)}' alt='Original'>"
               "<div class='after'><img alt='Output'></div><div class='bar'></div><div class='knob'>⇆</div>"
               "<span class='tag l'>original</span><span class='tag r'></span></div>"
               "<span class='muted' style='font-size:12px'>Drag the handle, or focus it and use ← →.</span></div>"
               "<div class='side'><div class='panel'><h3>Where the colour changed</h3>"
               "<img id='heat' alt='Colour drift heatmap'><div class='legend-bar'></div><div class='legend-ticks'>"
               f"<span>0 ΔE (unchanged)</span><span>{HEAT_MAX / 2:.0f}</span><span>{HEAT_MAX:.0f}+ ΔE</span></div>"
               "<p class='muted' style='font-size:12px'>Hue and chroma only: lightness changes are expected from "
               "relighting. Deep shadows and speculars are skipped.</p></div>")
    if logo_box:
        out.append("<div class='panel'><h3>Logo</h3><div class='pair'>"
                   f"<figure><img src='{crop_logo(rgb_in)}' alt='Original logo'><figcaption>original</figcaption></figure>"
                   "<figure><img id='logo-out' alt='Output logo'><figcaption id='logo-out-cap'></figcaption></figure>"
                   "</div></div>")
    out.append("<div class='panel'><h3>Gates</h3><dl class='kv' id='kv'></dl></div></div></div></section>")

    # gallery
    out.append("<section><h2>All outputs</h2><div class='gallery'>"
               + "".join(f"<figure data-id='{e(r['recipe'])}'><img src='{r['thumb']}' alt='{e(r['recipe'])}'>"
                         f"<figcaption><span style='font-size:12px'>{e(r['recipe'])}</span>"
                         f"<span class='chip {'ok' if r['_fails'] == 0 else 'bad'}'>"
                         f"{'✓ all' if r['_fails'] == 0 else str(r['_fails']) + ' ✕'}</span></figcaption></figure>"
                         for r in rows)
               + "</div></section>")

    # full data
    out.append("<section><h2>All measurements</h2><details><summary>Open the full table and definitions</summary>"
               "<div class='tablewrap' style='margin-top:12px'><table><thead><tr><th>Recipe</th>"
               + "".join(f"<th>{e(g[2])}</th>" for g in GATES) + "".join(f"<th>{e(i[1])}</th>" for i in INFO)
               + "</tr></thead><tbody>"
               + "".join("<tr><td>" + e(r["recipe"]) + "</td>"
                         + "".join(f"<td class='mono'>{fmt(g['value'], g['digits'])}</td>" for g in r["gates"])
                         + "".join(f"<td class='mono'>{fmt(r.get(i[0]))}</td>" for i in INFO) + "</tr>"
                         for r in rows)
               + "</tbody></table></div><dl class='kv' style='grid-template-columns:auto 1fr;margin-top:14px'>"
               + "".join(f"<dt>{e(g[2])}</dt><dd>{e(g[3])}</dd>" for g in GATES)
               + "".join(f"<dt>{e(i[1])}</dt><dd>{e(i[2])}</dd>" for i in INFO)
               + "</dl></details></section>")

    data = {"recipes": [{k: r[k] for k in ("recipe", "img", "heat", "logo")} |
                        {"gates": [{"question": g["question"], "value_fmt": g["value_fmt"], "ok": g["ok"]}
                                   for g in r["gates"]]} for r in rows]}
    out.append(f"<div class='tip' role='tooltip'></div><script type='application/json' id='data'>"
               f"{json.dumps(data)}</script><script>{JS}</script></div></body></html>")
    out_path = out_path or os.path.join(out_dir, f"{inp}_report.html")
    open(out_path, "w", encoding="utf8").write("".join(out))
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("bench_dir")
    ap.add_argument("input")
    ap.add_argument("outputs_dir")
    ap.add_argument("--notes")
    ap.add_argument("--out")
    a = ap.parse_args()
    print(build(a.bench_dir, a.input, a.outputs_dir, a.notes, a.out))
