"""Single-file HTML report from scores.json: verdict, trade-off chart, gate matrix, before/after
slider with a colour-drift heatmap, region crops, gallery and the full data. Images are embedded."""
import base64
import html
import io
import json
import os
from datetime import date

import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab

from ._assets import CSS
from .bench import stem
from .score import Pair, erode, find_mask

e = html.escape
HEAT_MAX = 10.0
RAMP = np.array([[0xcd, 0xe2, 0xfb], [0x86, 0xb6, 0xef], [0x2a, 0x78, 0xd6], [0x1c, 0x5c, 0xab],
                 [0x0d, 0x36, 0x6b]]) / 255.0

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const tip = document.querySelector('.tip');
document.querySelectorAll('.pt').forEach(g => {
  g.addEventListener('mousemove', ev => { tip.textContent = g.dataset.tip; tip.style.opacity = 1;
    tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 14) + 'px'; });
  g.addEventListener('mouseleave', () => tip.style.opacity = 0);
});
const ba = document.querySelector('.ba'), after = ba.querySelector('.after'), bar = ba.querySelector('.bar'),
      knob = ba.querySelector('.knob');
let pos = .5;
function setPos(p){ pos = Math.max(0, Math.min(1, p)); after.style.clipPath = `inset(0 0 0 ${pos*100}%)`;
  bar.style.left = knob.style.left = (pos*100) + '%'; }
let drag = false;
const move = ev => { const r = ba.getBoundingClientRect(); setPos((ev.clientX - r.left) / r.width); };
ba.addEventListener('pointerdown', ev => { drag = true; ba.setPointerCapture(ev.pointerId); move(ev); });
ba.addEventListener('pointermove', ev => drag && move(ev));
ba.addEventListener('pointerup', () => drag = false);
ba.tabIndex = 0;
ba.addEventListener('keydown', ev => { if (ev.key === 'ArrowLeft') setPos(pos - .05); if (ev.key === 'ArrowRight') setPos(pos + .05); });
let cur = {input: D.inputs[0], recipe: D.order[0]};
function chip(ok){ return ok === null ? '<span class="chip na">n/a</span>' : ok ? '<span class="chip ok">✓ pass</span>' : '<span class="chip bad">✕ fail</span>'; }
function show(){
  const r = D.items[cur.input + '|' + cur.recipe];
  ba.querySelector('img.before').src = D.originals[cur.input].img;
  const crop = document.getElementById('crop-in'); if (crop) crop.src = D.originals[cur.input].crop || '';
  if (!r) { ba.querySelector('.after img').removeAttribute('src'); ba.querySelector('.tag.r').textContent = 'no output';
    document.getElementById('kv').innerHTML = '<dt>No output for this combination.</dt>'; return; }
  ba.querySelector('.after img').src = r.img; ba.querySelector('.tag.r').textContent = cur.recipe;
  document.getElementById('heat').src = r.heat || '';
  const tp = document.getElementById('turn-panel'); tp.hidden = !r.turn; if (r.turn) document.getElementById('turn').src = r.turn;
  const co = document.getElementById('crop-out'); if (co) { co.src = r.crop || ''; document.getElementById('crop-out-cap').textContent = cur.recipe; }
  document.getElementById('kv').innerHTML = r.gates.map(g =>
    `<dt>${g.label}</dt><dd class="mono">${g.value}</dd><dd>${chip(g.pass)}</dd>`).join('');
  document.querySelectorAll('.picker button[data-id]').forEach(b => b.setAttribute('aria-pressed', b.dataset.id === cur.recipe));
  document.querySelectorAll('.picker button[data-in]').forEach(b => b.setAttribute('aria-pressed', b.dataset.in === cur.input));
}
document.querySelectorAll('[data-id]').forEach(el => el.addEventListener('click', () => {
  cur.recipe = el.dataset.id; if (el.dataset.in) cur.input = el.dataset.in; show();
  if (el.tagName === 'FIGURE') document.getElementById('compare').scrollIntoView({behavior:'smooth'}); }));
document.querySelectorAll('.picker button[data-in]').forEach(el => el.addEventListener('click', () => { cur.input = el.dataset.in; show(); }));
show();
"""


def uri(arr, width=None, quality=84):
    img = arr if isinstance(arr, Image.Image) else Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    if width and img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ramp(t):
    t = np.clip(t, 0, 1) * (len(RAMP) - 1)
    i = np.minimum(np.floor(t).astype(int), len(RAMP) - 2)
    f = (t - i)[..., None]
    return RAMP[i] * (1 - f) + RAMP[i + 1] * f


def heatmap(p, opt):
    spec = opt.get("region", "product")
    sel = erode(p.region(spec) & p.region(spec, "out"), opt.get("erode_pct", 0.15))
    if "l_range" in opt:
        lo, hi = opt["l_range"]
        sel &= (p.lab_in[..., 0] > lo) & (p.lab_in[..., 0] < hi) & (p.lab_out[..., 0] > lo) & (p.lab_out[..., 0] < hi)
    b = p.lab_out.copy()
    if opt.get("ignore_lightness"):
        b[..., 0] = p.lab_in[..., 0]
    de = deltaE_ciede2000(p.lab_in, b)
    out = 0.82 + 0.18 * np.repeat(p.rgb_out.mean(axis=2, keepdims=True), 3, axis=2)
    out[sel] = ramp(de[sel] / HEAT_MAX)
    return out


def fmtv(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 1 else f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"
    return str(v)


def gate_rows(item):
    out = []
    for m in item["metrics"]:
        if m["mode"] != "gate":
            continue
        v = m.get("values", {})
        val = fmtv(v.get("value")) + (f" · p95 {fmtv(v['p95'])}" if "p95" in v and "p95_max" in m["thresholds"] else "")
        out.append({"key": f"{m['dimension']}:{m['label']}", "dimension": m["dimension"], "label": m["label"],
                    "value": val if m["status"] == "ok" else m["status"].replace("_", " "),
                    "pass": m.get("pass") if m["status"] == "ok" else None})
    return out


def metric_value(item, label_or_cost):
    if label_or_cost == "cost":
        return item.get("cost")
    for m in item["metrics"]:
        if m["label"] == label_or_cost and m["status"] == "ok":
            return m["values"].get("mean", m["values"].get("value"))
    return None


def scatter(points, xlab, ylab, xgate=None, ygate=None):
    """points: [(name, x, y, fails)]. Gates: (value, 'min'|'max') draw the target zone."""
    W, H, ml, mr, mt, mb = 1100, 440, 64, 24, 20, 52
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    x0, x1 = min(xs + [xgate[0]] if xgate else xs), max(xs + [xgate[0]] if xgate else xs)
    y1 = max(ys + [ygate[0]] if ygate else ys)
    padx = (x1 - x0) * 0.12 or 0.1
    x0, x1, y0, y1 = x0 - padx, x1 + padx * 2.2, 0, y1 * 1.15 or 1
    sx = lambda v: ml + (v - x0) / (x1 - x0) * (W - ml - mr)
    sy = lambda v: mt + (1 - (v - y0) / (y1 - y0)) * (H - mt - mb)
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{e(ylab)} against {e(xlab)}">']
    if xgate and ygate:
        zx0, zx1 = (sx(xgate[0]), W - mr) if xgate[1] == "min" else (ml, sx(xgate[0]))
        zy0, zy1 = (sy(ygate[0]), sy(y0)) if ygate[1] == "max" else (mt, sy(ygate[0]))
        p.append(f'<rect x="{zx0:.1f}" y="{zy0:.1f}" width="{zx1 - zx0:.1f}" height="{zy1 - zy0:.1f}" class="zone"/>')
        p.append(f'<text x="{(zx1 - 6) if xgate[1] == "min" else (zx0 + 6):.1f}" y="{zy1 - 8:.1f}" class="zone-label" '
                 f'text-anchor="{"end" if xgate[1] == "min" else "start"}">Passes both</text>')
    for t in np.linspace(y0, y1, 5):
        p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(t):.1f}" y2="{sy(t):.1f}" class="grid"/>'
                 f'<text x="{ml - 8}" y="{sy(t) + 4:.1f}" class="tick" text-anchor="end">{fmtv(float(t))}</text>')
    for t in np.linspace(x0, x1, 6)[1:-1]:
        p.append(f'<text x="{sx(t):.1f}" y="{H - mb + 18}" class="tick" text-anchor="middle">{fmtv(float(t))}</text>')
    p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(y0):.1f}" y2="{sy(y0):.1f}" class="axis"/>')
    if xgate:
        p.append(f'<line x1="{sx(xgate[0]):.1f}" x2="{sx(xgate[0]):.1f}" y1="{mt}" y2="{sy(y0):.1f}" class="gate"/>')
    if ygate:
        p.append(f'<line x1="{ml}" x2="{W - mr}" y1="{sy(ygate[0]):.1f}" y2="{sy(ygate[0]):.1f}" class="gate"/>')
    p.append(f'<text x="{(ml + W - mr) / 2:.1f}" y="{H - 8}" class="axis-title" text-anchor="middle">{e(xlab)}</text>')
    p.append(f'<text transform="translate(14 {(mt + sy(y0)) / 2:.1f}) rotate(-90)" class="axis-title" '
             f'text-anchor="middle">{e(ylab)}</text>')
    placed = [(sx(x) - 6, sy(y) - 6, sx(x) + 6, sy(y) + 6) for _, x, y, _ in points]
    for name, x, y, fails in sorted(points, key=lambda q: q[2]):
        cx, cy, w = sx(x), sy(y), 6.6 * len(name)
        dx, dy, anchor = 10, 4, "start"
        for dx, dy, anchor in [(10, 4, "start"), (-10, 4, "end"), (10, -10, "start"), (10, 18, "start"),
                               (-10, -10, "end"), (-10, 18, "end")]:
            bx0 = cx + dx if anchor == "start" else cx + dx - w
            box = (bx0, cy + dy - 11, bx0 + w, cy + dy + 3)
            if box[0] >= ml and box[2] <= W - mr and box[1] >= mt and not any(
                    not (box[2] < q[0] or box[0] > q[2] or box[3] < q[1] or box[1] > q[3]) for q in placed):
                placed.append(box)
                break
        tipt = f"{name} · {xlab.split(' (')[0]} {fmtv(x)} · {ylab.split(' (')[0]} {fmtv(y)} · {fails} failed check(s)"
        p.append(f'<g class="pt" data-tip="{e(tipt)}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" class="hit"/>'
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot"/><text x="{cx + dx:.1f}" y="{cy + dy:.1f}" '
                 f'text-anchor="{anchor}" class="lbl">{e(name)}</text></g>')
    p.append("</svg>")
    return "<div class='chartwrap'>" + "".join(p) + "</div>"


def gate_of(scores, lab):
    for it in scores:
        for m in it["metrics"]:
            if m["label"] == lab and m["mode"] == "gate":
                t = m["thresholds"]
                for k, kind in (("min", "min"), ("dL_min", "min"), ("max", "max"), ("mean_max", "max"),
                                ("max_px", "max"), ("aspect_tolerance", "max")):
                    if k in t:
                        return (t[k], kind)
    return None


def build(b, out_dir, notes=None, listed=None, out_path=None):
    data = json.load(open(os.path.join(out_dir, "scores.json"), encoding="utf8"))
    scored, errors = data["scored"], data.get("errors", [])
    notes, listed = notes or {}, listed or {}
    inputs = {stem(i["path"]): i for i in b["inputs"]}
    in_order = [k for k in inputs if any(s["input"] == k for s in scored)]
    recipes = {r["id"]: r for r in b["recipes"]}

    # aggregate per recipe across inputs and seeds
    agg = {}
    for s in scored:
        g = gate_rows(s)
        a = agg.setdefault(s["recipe"], {"fails": 0, "checks": 0, "items": [], "costs": [], "lat": []})
        a["fails"] += sum(1 for x in g if x["pass"] is False)
        a["checks"] += sum(1 for x in g if x["pass"] is not None)
        a["items"].append(s)
        if s.get("cost") is not None:
            a["costs"].append(s["cost"])
        if s.get("latency_s") is not None:
            a["lat"].append(s["latency_s"])
    for rid, a in agg.items():
        a["cost"] = float(np.mean(a["costs"])) if a["costs"] else listed.get(rid)
        a["cost_src"] = "measured" if a["costs"] else "listed"
        a["latency"] = float(np.mean(a["lat"])) if a["lat"] else None
    order = sorted(agg, key=lambda r: (agg[r]["fails"], agg[r]["cost"] if agg[r]["cost"] is not None else 9))
    passing = [r for r in order if agg[r]["fails"] == 0 and agg[r]["checks"] > 0]
    measured = sum(sum(a["costs"]) for a in agg.values())
    not_run = sorted({m["label"] for s in scored for m in s["metrics"] if m["status"] != "ok"})
    attempted = {r["recipe"] for r in data.get("attempted", [])}
    missing = [rid for rid in recipes if rid not in agg and (rid in attempted or not attempted)]

    # media
    first_de = next((m for m in (b.get("evaluate") or {}).get("deviation", {}).get("metrics", [])
                     if m["id"] == "deltaE2000_region"), {"region": "product"})
    items, originals = {}, {}
    for k in in_order:
        inp = inputs[k]
        boxes = {n: v["box"] for n, v in (inp.get("regions") or {}).items() if isinstance(v, dict) and "box" in v}
        box = next(iter(boxes.values()), None)
        rgb_in = Pair(b, inp, os.path.join(b["_dir"], inp["path"]), None).rgb_in
        originals[k] = {"img": uri(rgb_in, 900)}
        if box:
            originals[k]["crop"] = uri(rgb_in[box[1]:box[3], box[0]:box[2]], 360, 90)
            originals[k]["crop_name"] = next(iter(boxes))
    for s in scored:
        if s.get("view"):  # 3D output: show its rendered front view
            p = Pair(b, inputs[s["input"]], os.path.join(out_dir, s["view"]), os.path.join(out_dir, s["view_mask"]))
        else:
            f = os.path.join(out_dir, s["file"])
            p = Pair(b, inputs[s["input"]], f, find_mask(out_dir, s["file"], s["recipe"]))
        it = {"img": uri(p.rgb_out, 900), "thumb": uri(p.rgb_out, 360, 80), "gates": gate_rows(s)}
        try:
            it["heat"] = uri(heatmap(p, first_de), 520)
        except KeyError:
            pass
        box = next(iter(p.boxes.values()), None)
        if box:
            it["crop"] = uri(p.rgb_out[box[1]:box[3], box[0]:box[2]], 360, 90)
        if s.get("turntable") and os.path.exists(os.path.join(out_dir, s["turntable"])):
            it["turn"] = uri(Image.open(os.path.join(out_dir, s["turntable"])).convert("RGB"), 900, 82)
        key = f"{s['input']}|{s['recipe']}"
        if key not in items or s["seed"] < items[key]["_seed"]:
            items[key] = {**it, "_seed": s["seed"]}

    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>Bench report</title><style>{CSS}</style></head>"
           f"<body><div class='wrap'>"]
    seeds = sorted({s["seed"] for s in scored})
    out.append("<header style='display:grid;gap:12px'>"
               f"<div class='muted mono' style='font-size:12px'>runware-eval · {date.today()}</div>"
               f"<h1>{e(b.get('title', 'Which recipe works best?'))}</h1><p class='ink2'>{e(b['goal'].strip())}</p>"
               f"<div class='meta'><span>{len(agg)} recipes</span><span>{len(in_order)} input(s)</span>"
               f"<span>seed(s) {', '.join(map(str, seeds))}</span><span>{len(scored)} outputs scored</span>"
               f"<span>Generation spend ${measured:.3f}</span>"
               f"<span>Checks spend ${data.get('judge_cost', 0) + sum(r.get('eval_cost') or 0 for r in data.get('attempted_rows', [])):.3f}</span>"
               f"<span>Judges: {e(', '.join(data.get('judges') or [])) or 'off'}</span></div></header>")
    best = order[0]
    cheapest_pass = min(passing, key=lambda r: agg[r]["cost"] or 9) if passing else None
    out.append("<section aria-label='Summary'><div class='cards'>"
               f"<div class='card'><span class='lab'>Recipes passing every check</span><span class='big'>"
               f"{len(passing)} / {len(agg)}</span><span class='lab'>{e(', '.join(passing)) or 'None yet'}</span></div>"
               f"<div class='card'><span class='lab'>{'Cheapest that passes' if cheapest_pass else 'Closest'}</span>"
               f"<span class='big' style='font-size:20px'>{e(cheapest_pass or best)}</span><span class='lab'>"
               + (f"${agg[cheapest_pass]['cost']:.4f} per image ({agg[cheapest_pass]['cost_src']})" if cheapest_pass
                  else f"{agg[best]['fails']} failed check(s) across all inputs") + "</span></div>"
               f"<div class='card'><span class='lab'>Checks not run</span><span class='big'>{len(not_run)}</span>"
               f"<span class='lab'>{e(', '.join(not_run)) or 'All ran'}</span></div>"
               f"<div class='card'><span class='lab'>Failed tasks</span><span class='big'>{len(errors)}</span>"
               f"<span class='lab'>{e(', '.join(sorted({x['recipe'] for x in errors}))) or 'None'}</span></div>"
               "</div></section>")

    if notes.get("findings") or notes.get("caveats") or missing or errors:
        out.append("<section><h2>What this run says</h2><ul class='notes'>")
        out += [f"<li>{n}</li>" for n in notes.get("findings", [])]
        out += [f"<li class='warn'>{n}</li>" for n in notes.get("caveats", [])]
        for x in errors:
            out.append(f"<li class='warn'><strong>{e(x['recipe'])}</strong> on {e(x['input'])} failed: "
                       f"{e(str(x.get('error')))}</li>")
        if missing:
            out.append(f"<li class='warn'><strong>No output in this folder:</strong> {e(', '.join(missing))}</li>")
        out.append("</ul></section>")

    # trade-off chart
    rep = b.get("report") or {}
    xlab, ylab = rep.get("x", "cost"), rep.get("y") or next(
        (m["label"] for m in scored[0]["metrics"] if m["id"] == "deltaE2000_region" and m["status"] == "ok"), None)
    if ylab:
        pts = []
        for rid in order:
            xs = [metric_value(i, xlab) for i in agg[rid]["items"]] if xlab != "cost" else [agg[rid]["cost"]]
            ys = [metric_value(i, ylab) for i in agg[rid]["items"]]
            xs, ys = [v for v in xs if v is not None], [v for v in ys if v is not None]
            if xs and ys:
                pts.append((rid, float(np.mean(xs)), float(np.mean(ys)), agg[rid]["fails"]))
        if pts:
            xname = "Cost per image (USD) →" if xlab == "cost" else f"{xlab} →"
            out.append("<section><h2>The trade-off</h2><p class='ink2'>Averages across inputs. Dashed lines are the "
                       "pass thresholds; the shaded area passes both. Hover a dot for values.</p>"
                       + scatter(pts, xname, f"{ylab} ↓ better" if (gate_of(scored, ylab) or (0, 'max'))[1] == "max"
                                 else f"{ylab} ↑ better", gate_of(scored, xlab) if xlab != "cost" else None,
                                 gate_of(scored, ylab)) + "</section>")

    # gate matrix (aggregated: worst case across inputs and seeds)
    cols = []
    for s in scored:
        for g in gate_rows(s):
            if g["key"] not in [c["key"] for c in cols]:
                cols.append(g)
    groups = []
    for c in cols:
        if not groups or groups[-1][0] != c["dimension"]:
            groups.append([c["dimension"], 0])
        groups[-1][1] += 1
    out.append("<section><h2>Check by check</h2><p class='ink2'>A cell fails if the check failed on any input or "
               "seed. Ranked by failed checks, then cost. Thresholds come from <span class='mono'>bench.yaml</span>.</p>"
               "<div class='tablewrap'><table><thead><tr><th></th><th></th>"
               + "".join(f"<th class='grp' colspan='{n}'>{e(d.replace('_', ' '))}</th>" for d, n in groups)
               + "<th></th><th></th></tr><tr><th>#</th><th>Recipe</th>"
               + "".join(f"<th>{e(c['label'])}</th>" for c in cols) + "<th>$/image</th><th>Time</th></tr></thead><tbody>")
    for n, rid in enumerate(order, 1):
        a, cells = agg[rid], []
        for c in cols:
            vals = [g for it in a["items"] for g in gate_rows(it) if g["key"] == c["key"]]
            ok = [g["pass"] for g in vals if g["pass"] is not None]
            if not ok:
                cells.append("<td><span class='chip na'>not run</span></td>")
                continue
            worst = next((g for g in vals if g["pass"] is False), vals[0])
            cells.append(f"<td><span class='chip {'ok' if all(ok) else 'bad'}'>{'✓' if all(ok) else '✕'} "
                         f"<span class='mono'>{e(worst['value'])}</span></span></td>")
        cost = f"${a['cost']:.4f}" + ("" if a["cost_src"] == "measured" else "*") if a["cost"] is not None else "—"
        lat = f"{a['latency']:.0f}s" if a["latency"] else "—"
        out.append(f"<tr><td class='rank'>{n}</td><td><button data-id='{e(rid)}' style='all:unset;cursor:pointer;"
                   f"font-weight:600'>{e(rid)}</button><div class='muted mono' style='font-size:11px'>"
                   f"{e(recipes.get(rid, {}).get('model', ''))} · {e(recipes.get(rid, {}).get('_fp', '') or '')[:8]}</div></td>{''.join(cells)}"
                   f"<td class='mono'>{cost}</td><td class='mono'>{lat}</td></tr>")
    out.append("</tbody></table></div><p class='muted' style='font-size:12px'>* listed price (no measured cost for this recipe yet).</p></section>")

    # comparison viewer
    crop_name = next((o.get("crop_name") for o in originals.values() if o.get("crop_name")), None)
    out.append("<section id='compare'><h2>Compare with the original</h2>")
    if len(in_order) > 1:
        out.append("<div class='picker' role='group' aria-label='Input'>" + "".join(
            f"<button data-in='{e(k)}' aria-pressed='false'>{e(k)}</button>" for k in in_order) + "</div>")
    out.append("<div class='picker' role='group' aria-label='Recipe'>" + "".join(
        f"<button data-id='{e(r)}' aria-pressed='false'>{e(r)}<span class='n'>{agg[r]['fails']}✕</span></button>"
        for r in order) + "</div><div class='split'><div style='display:grid;gap:6px'>"
        "<div class='ba' aria-label='Drag to compare original and output'><img class='before' alt='Original'>"
        "<div class='after'><img alt='Output'></div><div class='bar'></div><div class='knob'>⇆</div>"
        "<span class='tag l'>original</span><span class='tag r'></span></div><span class='muted' "
        "style='font-size:12px'>Drag the handle, or focus it and use ← →.</span></div><div class='side'>"
        "<div class='panel'><h3>Where the colour changed</h3><img id='heat' alt='Colour drift heatmap'>"
        "<div class='legend-bar'></div><div class='legend-ticks'><span>0 ΔE (unchanged)</span><span>"
        f"{HEAT_MAX / 2:.0f}</span><span>{HEAT_MAX:.0f}+ ΔE</span></div><p class='muted' style='font-size:12px'>"
        f"Same settings as the first colour check{' (hue and chroma only)' if first_de.get('ignore_lightness') else ''}."
        "</p></div>")
    if crop_name:
        out.append(f"<div class='panel'><h3>{e(crop_name.capitalize())}</h3><div class='pair'><figure><img id='crop-in' "
                   "alt='Original crop'><figcaption>original</figcaption></figure><figure><img id='crop-out' "
                   "alt='Output crop'><figcaption id='crop-out-cap'></figcaption></figure></div></div>")
    out.append("<div class='panel' id='turn-panel' hidden><h3>All around (0°, 90°, 180°, 270°)</h3>"
               "<img id='turn' alt='Turntable views of the 3D model'></div>")
    out.append("<div class='panel'><h3>Checks</h3><dl class='kv' id='kv'></dl></div></div></div></section>")

    # gallery
    out.append("<section><h2>All outputs</h2>")
    for k in in_order:
        if len(in_order) > 1:
            out.append(f"<h3 class='ink2'>{e(k)}</h3>")
        out.append("<div class='gallery'>")
        for rid in order:
            it = items.get(f"{k}|{rid}")
            if not it:
                continue
            f = sum(1 for g in it["gates"] if g["pass"] is False)
            out.append(f"<figure data-id='{e(rid)}' data-in='{e(k)}'><img src='{it['thumb']}' alt='{e(rid)}'>"
                       f"<figcaption><span style='font-size:12px'>{e(rid)}</span><span class='chip "
                       f"{'ok' if f == 0 else 'bad'}'>{'✓ all' if f == 0 else str(f) + ' ✕'}</span></figcaption></figure>")
        out.append("</div>")
    out.append("</section>")

    # full data
    labels = []
    for s in scored:
        for m in s["metrics"]:
            if m["label"] not in labels:
                labels.append(m["label"])
    out.append("<section><h2>All measurements</h2><details><summary>Open the full table</summary><div class='tablewrap' "
               "style='margin-top:12px'><table><thead><tr><th>Input</th><th>Recipe</th><th>Seed</th><th>Native</th>"
               "<th>Cost</th><th>Time</th>" + "".join(f"<th>{e(l)}</th>" for l in labels) + "</tr></thead><tbody>")
    for s in sorted(scored, key=lambda s: (s["input"], order.index(s["recipe"]), s["seed"])):
        byl = {m["label"]: m for m in s["metrics"]}
        cells = "".join(f"<td class='mono'>{fmtv(byl[l]['values'].get('value')) if l in byl and byl[l]['status'] == 'ok' else '—'}</td>"
                        for l in labels)
        out.append(f"<tr><td>{e(s['input'])}</td><td>{e(s['recipe'])}</td><td>{s['seed']}</td><td class='mono'>"
                   f"{e(s['native'])}</td><td class='mono'>{fmtv(s.get('cost'))}</td><td class='mono'>"
                   f"{fmtv(s.get('latency_s'))}</td>{cells}</tr>")
    out.append("</tbody></table></div></details></section>")

    payload = {"inputs": in_order, "order": order, "originals": originals,
               "items": {k: {kk: vv for kk, vv in v.items() if kk not in ("thumb", "_seed")} for k, v in items.items()}}
    out.append(f"<div class='tip' role='tooltip'></div><script type='application/json' id='data'>{json.dumps(payload)}"
               f"</script><script>{JS}</script></div></body></html>")
    out_path = out_path or os.path.join(out_dir, "report.html")
    open(out_path, "w", encoding="utf8").write("".join(out))
    return out_path
