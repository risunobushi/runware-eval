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

from ._assets import CSS, FONTS
from .bench import stem
from .score import Pair, erode, find_mask

e = html.escape
HEAT_MAX = 10.0
# Runware greens to yellow, dark to light: brighter = more colour change (matches .legend-bar in _assets)
RAMP = np.array([[0x1f, 0x3a, 0x1b], [0x34, 0x5c, 0x2d], [0x6f, 0xbf, 0x5f], [0xaf, 0xff, 0x9f],
                 [0xff, 0xff, 0x7d]]) / 255.0

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
    out = 0.06 + 0.30 * np.repeat(p.rgb_out.mean(axis=2, keepdims=True), 3, axis=2)  # dim grey under the ramp
    out[sel] = ramp(de[sel] / HEAT_MAX)
    return out


def seed_verdict(passes, rule="majority"):
    """Verdict over the seeds of one input: majority (more than half), all, or any."""
    if rule == "all":
        return all(passes)
    if rule == "any":
        return any(passes)
    return sum(passes) * 2 > len(passes)


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
                 f'text-anchor="{"end" if xgate[1] == "min" else "start"}">PASSES BOTH</text>')
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
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot{" fail" if fails else ""}"/><text x="{cx + dx:.1f}" y="{cy + dy:.1f}" '
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

    # aggregate per recipe: seeds are judged by `pass_rule` within each input (one unlucky or lucky seed
    # does not decide), then a recipe must pass a check on every input
    rule = b.get("pass_rule", "majority")
    agg = {}
    for s in scored:
        a = agg.setdefault(s["recipe"], {"items": [], "costs": [], "lat": [], "by_check": {}})
        for g in gate_rows(s):
            if g["pass"] is not None:
                a["by_check"].setdefault(g["key"], {}).setdefault(s["input"], []).append(g["pass"])
        a["items"].append(s)
        if s.get("cost") is not None:
            a["costs"].append(s["cost"])
        if s.get("latency_s") is not None:
            a["lat"].append(s["latency_s"])
    for rid, a in agg.items():
        a["verdict"] = {k: all(seed_verdict(v, rule) for v in by_in.values()) for k, by_in in a["by_check"].items()}
        a["fails"] = sum(1 for v in a["verdict"].values() if not v)
        a["checks"] = len(a["verdict"])
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
        strip = [recipes.get(s["recipe"], {}).get("model", "")]
        if s.get("latency_s") is not None:
            strip.append(f"{s['latency_s']:.1f}s")
        if s.get("cost") is not None:
            strip.append(f"${s['cost']:.4f}")
        it = {"img": uri(p.rgb_out, 900), "thumb": uri(p.rgb_out, 360, 80), "gates": gate_rows(s),
              "strip": " · ".join(x for x in strip if x)}
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

    title = b.get("title") or "Which recipe works best?"
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>{e(title)}</title>{FONTS}<style>{CSS}</style></head>"
           f"<body><div class='wrap'>"]
    seeds = sorted({s["seed"] for s in scored})
    best = order[0]
    cheapest_pass = min(passing, key=lambda r: agg[r]["cost"] or 9) if passing else None
    # headline: the count, then the number that decides
    if cheapest_pass and agg[cheapest_pass]["cost"] is not None:
        headline = (f"{len(passing)} of {len(agg)} recipes pass every check. "
                    f"Cheapest: <em>${agg[cheapest_pass]['cost']:.3f}</em> per output.")
    elif passing:
        headline = f"{len(passing)} of {len(agg)} recipes pass every check."
    else:
        headline = (f"0 of {len(agg)} recipes pass every check. "
                    f"Fewest failed checks: <em>{agg[best]['fails']}</em>.")
    controls = data.get("controls", [])
    checks_spend = data.get("judge_cost", 0) + sum(r.get("eval_cost") or 0 for r in data.get("attempted_rows", []))
    out.append("<header class='hero'>"
               f"<div class='kicker'><b>runware-eval</b> · bench report · {date.today()}</div>"
               f"<h1>{headline}</h1><p class='goal'><strong>{e(title)}</strong> {e(b['goal'].strip())}</p>"
               f"<div class='meta'><span>{len(agg)} recipes</span><span>{len(in_order)} input(s)</span>"
               f"<span>seed {', '.join(map(str, seeds))}</span><span>{len(scored)} outputs</span>"
               f"<span>generation ${measured:.3f}</span><span>checks ${checks_spend:.3f}</span>"
               f"<span>judges {e(', '.join(data.get('judges') or [])) or 'off'}</span>"
               f"<span>controls {sum(c['ok'] for c in controls)}/{len(controls)} ok</span>"
               "</div></header>")

    def card(label, big, foot, lit=False):
        return (f"<div class='card{' lit' if lit else ''}'><span class='lab'>{label}</span>"
                f"<span class='big'>{big}</span><span class='strip'>{foot}</span></div>")

    if cheapest_pass:
        c = agg[cheapest_pass]
        second = card("Cheapest that passes", f"${c['cost']:.3f}" if c["cost"] is not None else "—",
                      f"{e(cheapest_pass)} · {e(recipes.get(cheapest_pass, {}).get('model', ''))} · {c['cost_src']}")
    else:
        second = card("Fewest failed checks", agg[best]["fails"],
                      f"{e(best)} · {e(recipes.get(best, {}).get('model', ''))}")
    out.append("<section aria-label='Summary'><div class='cards'>"
               + card("Pass every check", f"{len(passing)}/{len(agg)}", e(", ".join(passing)) or "none yet",
                      lit=bool(passing))
               + second
               + card("Checks not run", len(not_run), e(", ".join(not_run)) or "all ran")
               + card("Failed tasks", len(errors), e(", ".join(sorted({x["recipe"] for x in errors}))) or "none")
               + "</div></section>")

    sec_n = [0]

    def sec_head(h2, intro=""):
        sec_n[0] += 1
        return (f"<div class='sec-head'><h2><span class='num'>{sec_n[0]:02d}</span>{h2}</h2>"
                + (f"<p class='ink2'>{intro}</p>" if intro else "") + "</div>")

    bad_ctl = [c for c in data.get("controls", []) if not c["ok"]]
    if notes.get("findings") or notes.get("caveats") or missing or errors or bad_ctl:
        out.append("<section>" + sec_head("Findings") + "<ul class='notes'>")
        out += [f"<li>{n}</li>" for n in notes.get("findings", [])]
        out += [f"<li class='warn'>{n}</li>" for n in notes.get("caveats", [])]
        for c in bad_ctl:
            out.append(f"<li class='warn'><strong>Control failed:</strong> {e(c['label'])} on an unchanged copy of "
                       f"{e(c['input'])}: {fmtv(c['value'])}, {'failed' if c['expected_pass'] else 'passed'} "
                       f"(expected {'pass' if c['expected_pass'] else 'fail'}). Check or threshold does not fit "
                       f"this bench.</li>")
        for x in errors:
            out.append(f"<li class='warn'><strong>{e(x['recipe'])}</strong> on {e(x['input'])} failed: "
                       f"{e(str(x.get('error')))}</li>")
        if missing:
            out.append(f"<li class='warn'><strong>No output in this folder:</strong> {e(', '.join(missing))}</li>")
        out.append("</ul></section>")

    # calibration and human ranking (from the labeling page)
    cal_path = os.path.join(out_dir, "calibration.json")
    if os.path.exists(cal_path):
        cal = json.load(open(cal_path, encoding="utf8"))
        out.append("<section>" + sec_head(
            "Checks vs your labels",
            f"{cal['labeled']} outputs labeled blind ({cal['good']} good). Balanced agreement: 50% = chance. "
            f"{'Few labels: treat suggestions as hints. ' if cal.get('few_labels') else ''}Suggestions are not "
            f"applied to <span class='mono'>bench.yaml</span>."))
        if cal.get("gates"):
            out.append("<div class='tablewrap'><table><thead><tr><th>Check</th><th>Threshold</th><th>Agrees with you"
                       "</th><th>Suggested</th><th>Would agree</th></tr></thead><tbody>"
                       + "".join(f"<tr><td>{e(g['label'])}</td><td class='mono'>{e(g['key'])}: {fmtv(g['threshold_now'])}"
                                 f"</td><td class='mono'>{g['agreement_now']:.0%}</td><td class='mono'>"
                                 f"{fmtv(g['suggested']) if g['suggested'] != g['threshold_now'] else '—'}</td>"
                                 f"<td class='mono'>{g['agreement_suggested']:.0%}</td></tr>" for g in cal["gates"])
                       + "</tbody></table></div>")
        if cal.get("ranks"):
            out.append("<div class='tablewrap'><table><thead><tr><th>Rank metric</th><th>Orders your good above "
                       "your bad (AUC)</th></tr></thead><tbody>"
                       + "".join(f"<tr><td>{e(r['label'])}</td><td class='mono'>{r['auc']:.2f}"
                                 f"{' · weak' if r['auc'] < 0.7 else ''}</td></tr>" for r in cal["ranks"])
                       + "</tbody></table></div>")
        if cal.get("human_ranking"):
            hr = sorted(cal["human_ranking"].items(), key=lambda x: -x[1]["score"])
            out.append("<h3>Human ranking</h3><div class='tablewrap'><table><thead><tr><th>#</th><th>Recipe</th>"
                       "<th>Score (1.0 = average)</th><th>Wins</th></tr></thead><tbody>"
                       + "".join(f"<tr><td class='rank'>{i}</td><td>{e(r)}</td><td class='mono'>{v['score']:.2f}</td>"
                                 f"<td class='mono'>{v['wins']:g} / {v['games']:g}</td></tr>"
                                 for i, (r, v) in enumerate(hr, 1))
                       + "</tbody></table></div>")
        out.append("</section>")

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
            out.append("<section>" + sec_head(
                ("Cost" if xlab == "cost" else e(xlab)) + f" vs {e(ylab)}",
                "Mean across inputs. Dashed: pass thresholds. Filled: passes every check.")
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
    rule_txt = {"majority": "most seeds", "all": "every seed", "any": "at least one seed"}.get(rule, rule)
    out.append("<section>" + sec_head(
               "Checks by recipe",
               f"Pass = passes on {rule_txt} of every input (<span class='mono'>pass_rule: {e(rule)}</span>). "
               "Cells: outputs passed / total. Sorted by failed checks, then cost.")
               + "<div class='tablewrap'><table><thead><tr><th></th><th></th>"
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
            v = a["verdict"].get(c["key"], all(ok))
            shown = (f"{sum(ok)}/{len(ok)}" if len(ok) > 1
                     else next((g for g in vals if g["pass"] is not None), vals[0])["value"])
            cells.append(f"<td><span class='chip {'ok' if v else 'bad'}' title='passed on {sum(ok)} of {len(ok)} "
                         f"outputs (inputs x seeds)'>{'✓' if v else '✕'} <span class='mono'>{e(str(shown))}"
                         f"</span></span></td>")
        cost = f"${a['cost']:.4f}" + ("" if a["cost_src"] == "measured" else "*") if a["cost"] is not None else "—"
        lat = f"{a['latency']:.0f}s" if a["latency"] else "—"
        out.append(f"<tr><td class='rank'>{n}</td><td><button data-id='{e(rid)}' class='linkish'>{e(rid)}</button><div class='strip'>"
                   f"{e(recipes.get(rid, {}).get('model', ''))} · {e(recipes.get(rid, {}).get('_fp', '') or '')[:8]}</div></td>{''.join(cells)}"
                   f"<td class='mono'>{cost}</td><td class='mono'>{lat}</td></tr>")
    out.append("</tbody></table></div><p class='muted' style='font-size:12px'>* listed price, not measured.</p></section>")

    # comparison viewer
    crop_name = next((o.get("crop_name") for o in originals.values() if o.get("crop_name")), None)
    out.append("<section id='compare'>" + sec_head("Output vs original"))
    if len(in_order) > 1:
        out.append("<div class='picker' role='group' aria-label='Input'>" + "".join(
            f"<button data-in='{e(k)}' aria-pressed='false'>{e(k)}</button>" for k in in_order) + "</div>")
    out.append("<div class='picker' role='group' aria-label='Recipe'>" + "".join(
        f"<button data-id='{e(r)}' aria-pressed='false'>{e(r)}<span class='n'>{agg[r]['fails']}✕</span></button>"
        for r in order) + "</div><div class='split'><div style='display:grid;gap:6px'>"
        "<div class='ba' aria-label='Drag to compare original and output'><img class='before' alt='Original'>"
        "<div class='after'><img alt='Output'></div><div class='bar'></div><div class='knob'>⇆</div>"
        "<span class='tag l'>original</span><span class='tag r'></span></div><span class='muted' "
        "style='font-size:12px'>Drag, or use ← → when focused.</span></div><div class='side'>"
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
    out.append("<section>" + sec_head("Outputs", "First seed per recipe: model · time · cost. Click to compare."))
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
                       f"<figcaption><span class='row1'><span>{e(rid)}</span><span class='chip "
                       f"{'ok' if f == 0 else 'bad'}'>{'✓ all' if f == 0 else str(f) + ' ✕'}</span></span>"
                       f"<span class='strip'>{e(it['strip'])}</span></figcaption></figure>")
        out.append("</div>")
    out.append("</section>")

    # full data
    labels = []
    for s in scored:
        for m in s["metrics"]:
            if m["label"] not in labels:
                labels.append(m["label"])
    out.append("<section>" + sec_head("All measurements") + "<details><summary>Show table</summary><div class='tablewrap' "
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

    out.append("<section class='cta'><div style='display:grid;gap:8px'><h2>Re-run</h2><p class='ink2'>Add a "
               "recipe file and run again. Outputs already measured are reused by fingerprint.</p></div>"
               "<code>runware-eval run bench.yaml</code></section>")

    payload = {"inputs": in_order, "order": order, "originals": originals,
               "items": {k: {kk: vv for kk, vv in v.items() if kk not in ("thumb", "_seed", "strip")} for k, v in items.items()}}
    out.append(f"<div class='tip' role='tooltip'></div><script type='application/json' id='data'>{json.dumps(payload)}"
               f"</script><script>{JS}</script></div></body></html>")
    out_path = out_path or os.path.join(out_dir, "report.html")
    open(out_path, "w", encoding="utf8").write("".join(out))
    return out_path
