"""Single-file HTML report from scores.json: verdict, trade-off chart, gate matrix, before/after
slider with a colour-drift heatmap, region crops, gallery and the full data. Images are embedded."""
import base64
import html
import io
import json
import os
import re
from datetime import date

import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab

from . import _labeling, catalog
from ._assets import CSS, FONTS
from .bench import ROUTER, stem
from .score import JUDGED, Pair, coverage, erode, find_mask, label as metric_label, metric_id

e = html.escape
HEAT_MAX = 10.0
CLIP_BUDGET_MB = 30  # embedded video previews in one report; beyond it, clips stay as files in the run folder
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
document.querySelectorAll('.ba').forEach(el => {
  const after = el.querySelector('.after'), bar = el.querySelector('.bar'), knob = el.querySelector('.knob');
  let pos = .5, drag = false;
  function setPos(p){ pos = Math.max(0, Math.min(1, p)); after.style.clipPath = `inset(0 0 0 ${pos*100}%)`;
    bar.style.left = knob.style.left = (pos*100) + '%'; }
  const move = ev => { const r = el.getBoundingClientRect(); setPos((ev.clientX - r.left) / r.width); };
  el.addEventListener('pointerdown', ev => { drag = true; el.setPointerCapture(ev.pointerId); move(ev); });
  el.addEventListener('pointermove', ev => drag && move(ev));
  el.addEventListener('pointerup', () => drag = false);
  el.tabIndex = 0;
  el.addEventListener('keydown', ev => { if (ev.key === 'ArrowLeft') setPos(pos - .05); if (ev.key === 'ArrowRight') setPos(pos + .05); });
});
const ba = document.querySelector('.ba');
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
  const tp = document.getElementById('turn-panel'); tp.hidden = !r.turn; if (r.turn) { document.getElementById('turn').src = r.turn;
    document.getElementById('turn-title').textContent = r.turn_title || 'Views'; }
  const cp = document.getElementById('clip-panel'), cv = document.getElementById('clip'); cp.hidden = !r.clip;
  if (r.clip) { if (cv.getAttribute('src') !== r.clip) cv.src = r.clip; } else { cv.pause(); cv.removeAttribute('src'); }
  const co = document.getElementById('crop-out'); if (co) { co.src = r.crop || ''; document.getElementById('crop-out-cap').textContent = cur.recipe; }
  document.getElementById('kv').innerHTML = r.gates.map(g =>
    `<dt>${g.label}</dt><dd class="mono">${g.value}</dd><dd>${g.gate ? chip(g.pass) : ''}</dd>`).join('');
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


def gate_rows(item, every=False):
    """The checks with a limit; with `every`, the measurements without one too (their `pass` is None)."""
    out = []
    for m in item["metrics"]:
        if m["mode"] != "gate" and not every:
            continue
        v = m.get("values", {})
        val = fmtv(v.get("value")) + (f" · p95 {fmtv(v['p95'])}" if "p95" in v and "p95_max" in m["thresholds"] else "")
        out.append({"key": f"{m['dimension']}:{m['label']}", "dimension": m["dimension"], "label": m["label"],
                    "value": val if m["status"] == "ok" else m["status"].replace("_", " "),
                    "gate": m["mode"] == "gate",
                    "pass": m.get("pass") if m["status"] == "ok" and m["mode"] == "gate" else None})
    return out


def place_recipes(b, scored, agg):
    """Mean of every measurement per recipe, and each recipe's place on it (1 = best, ties share a place).

    A measurement is placed when it has a better direction and every recipe has a value for it, so no
    recipe gains from a measurement it skipped. Places are averaged inside a dimension, then across
    dimensions: the dimensions are what the user chose, and each counts once however many measurements
    it holds. Returns (columns, direction by key, placed keys)."""
    reg = catalog.load(b)
    direction = {}
    for dim, spec in (b.get("evaluate") or {}).items():
        for opt in spec.get("metrics", []):
            meta = (reg.get(metric_id(opt)) or {}).get("meta", {})
            direction[f"{dim}:{metric_label(opt)}"] = "higher" if opt["id"] in JUDGED else meta.get("direction", "")
    cols, seen = [], {}
    for s in scored:
        for m in s["metrics"]:
            k = f"{m['dimension']}:{m['label']}"
            if k not in seen:
                seen[k] = {}
                cols.append({"key": k, "dimension": m["dimension"], "label": m["label"]})
            v = (m.get("values") or {}).get("mean", (m.get("values") or {}).get("value")) if m["status"] == "ok" else None
            if isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v):
                seen[k].setdefault(s["recipe"], []).append(float(v))
    placed = []
    for a in agg.values():
        a["means"], a["places"] = {}, {}
    for c in cols:
        k, by = c["key"], seen[c["key"]]
        for r, vs in by.items():
            agg[r]["means"][k] = float(np.mean(vs))
        d = direction.get(k)
        if d not in ("lower", "higher", "closer_to_zero") or any(r not in by for r in agg):
            continue
        cost = {r: (-m if d == "higher" else abs(m) if d == "closer_to_zero" else m)
                for r, m in ((r, agg[r]["means"][k]) for r in agg)}
        for r in agg:
            ties = sum(1 for q in agg if np.isclose(cost[q], cost[r], rtol=1e-6, atol=1e-9))
            better = sum(1 for q in agg if cost[q] < cost[r] and not np.isclose(cost[q], cost[r], rtol=1e-6, atol=1e-9))
            agg[r]["places"][k] = 1 + better + (ties - 1) / 2
        placed.append(k)
    for a in agg.values():
        by_dim = {}
        for c in cols:
            if c["key"] in placed:
                by_dim.setdefault(c["dimension"], []).append(a["places"][c["key"]])
        a["place_by_dim"] = {d: float(np.mean(v)) for d, v in by_dim.items()}
        a["place"] = float(np.mean(list(a["place_by_dim"].values()))) if by_dim else None
    return cols, direction, placed


def metric_value(item, label_or_cost):
    if label_or_cost == "cost":
        return item.get("cost")
    for m in item["metrics"]:
        if m["label"] == label_or_cost and m["status"] == "ok":
            return m["values"].get("mean", m["values"].get("value"))
    return None


BETTER = {"lower": "Less=Better", "higher": "More=Better", "closer_to_zero": "Closer to 0=Better"}


def split_note(text):
    """A note as (lead, rest): its bold opening, else its first sentence. The report shows the lead and folds the rest."""
    m = re.match(r"\s*(<(b|strong)>.*?</\2>)[\s:.]*(.*)", text, re.S) or re.match(r"(.*?[.:])\s+(.*)", text, re.S)
    if not m:
        return text.strip(), ""
    lead, rest = m.group(1).strip(), m.groups()[-1].strip()
    return lead[:-1] if lead.endswith(":") else lead, rest[:1].upper() + rest[1:]


def note(lead, rest="", warn=False):
    cls = " class='warn'" if warn else ""
    if not rest:
        return f"<li{cls}><div class='lead'>{lead}</div></li>"
    return f"<li{cls}><details><summary>{lead}</summary><div class='more'>{rest}</div></details></li>"


def scatter(points, xname, yname, xnote="", ynote="", xgate=None, ygate=None):
    """points: [(name, x, y, fails)]. Gates: (value, 'min'|'max') draw the target zone; with a gate, dots
    are coloured by whether they sit inside it, otherwise by whether the recipe fails any check."""
    W, H, ml, mr, mt, mb = 1100, 440, 78, 24, 20, 56
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    x0, x1 = min(xs + [xgate[0]] if xgate else xs), max(xs + [xgate[0]] if xgate else xs)
    y1 = max(ys + [ygate[0]] if ygate else ys)
    padx = (x1 - x0) * 0.12 or 0.1
    x0, x1, y0, y1 = x0 - padx, x1 + padx * 2.2, 0, y1 * 1.15 or 1
    sx = lambda v: ml + (v - x0) / (x1 - x0) * (W - ml - mr)
    sy = lambda v: mt + (1 - (v - y0) / (y1 - y0)) * (H - mt - mb)
    within = lambda v, g: g is None or (v >= g[0] if g[1] == "min" else v <= g[0])
    gated = bool(xgate or ygate)
    xtitle, ytitle = (f"{n} ({note})" if note else n for n, note in ((xname, xnote), (yname, ynote)))
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{e(yname)} against {e(xname)}">']
    if gated:
        zx0, zx1 = (ml, W - mr) if not xgate else (sx(xgate[0]), W - mr) if xgate[1] == "min" else (ml, sx(xgate[0]))
        zy0, zy1 = (mt, sy(y0)) if not ygate else (sy(ygate[0]), sy(y0)) if ygate[1] == "max" else (mt, sy(ygate[0]))
        right = bool(xgate) and xgate[1] == "min"
        p.append(f'<rect x="{zx0:.1f}" y="{zy0:.1f}" width="{zx1 - zx0:.1f}" height="{zy1 - zy0:.1f}" class="zone"/>')
        p.append(f'<text x="{(zx1 - 6) if right else (zx0 + 6):.1f}" y="{zy1 - 8:.1f}" class="zone-label" '
                 f'text-anchor="{"end" if right else "start"}">WITHIN {"BOTH LIMITS" if xgate and ygate else "THE LIMIT"}</text>')
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
    p.append(f'<text x="{(ml + W - mr) / 2:.1f}" y="{H - 10}" class="axis-title" text-anchor="middle">{e(xtitle)}</text>')
    p.append(f'<text transform="translate(20 {(mt + sy(y0)) / 2:.1f}) rotate(-90)" class="axis-title" '
             f'text-anchor="middle">{e(ytitle)}</text>')
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
        inside = within(x, xgate) and within(y, ygate)
        cls = (" in" if inside else " out") if gated else (" fail" if fails else "")
        tipt = (f"{name} · {xname} {fmtv(x)} · {yname} {fmtv(y)} · "
                + (("within" if inside else "outside") + " the limits shown · " if gated else "") + f"{fails} failed check(s)")
        p.append(f'<g class="pt{cls}" data-tip="{e(tipt)}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" class="hit"/>'
                 f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot{cls}"/><text x="{cx + dx:.1f}" y="{cy + dy:.1f}" '
                 f'text-anchor="{anchor}" class="lbl">{e(name)}</text></g>')
    p.append("</svg>")
    return "<div class='chartwrap'>" + "".join(p) + "</div>"


def short_model(air):
    return air.split(":", 1)[-1] if air else "?"


def router_rows(agg, order, recipes, errors, best):
    """One row per `model: auto` recipe: what the router picked on each call, how those outputs did
    against the checks, and how the same model did when the bench called it by name."""
    by_model = {}
    for rid in order:
        m = recipes.get(rid, {}).get("model")
        if m and m != ROUTER:
            by_model.setdefault(m, []).append(rid)
    rows = []
    for rid in order:
        r = recipes.get(rid, {})
        if r.get("model") != ROUTER:
            continue
        a, picks, by_pick = agg[rid], {}, {}
        for s in a["items"]:
            m = s.get("picked_model") or "not recorded"
            picks[m] = picks.get(m, 0) + 1
            by_pick.setdefault(m, []).append(sum(1 for g in gate_rows(s) if g["pass"] is False))
        rt = r.get("routing") or {}
        pref = rt.get("preferences")
        pool = rt.get("allowedModels")
        settings = [("pool: this bench's models" if pool == "bench" else f"pool: {len(pool)} listed models" if pool
                     else f"pool: catalog minus {len(rt['excludedModels'])}" if rt.get("excludedModels")
                     else "pool: whole catalog"),
                    " · ".join(f"{k} {v}" for k, v in pref.items()) if pref else "even weights"]
        if rt.get("maxPrice") is not None:
            settings.append(f"max ${rt['maxPrice']}")
        rows.append({"id": rid, "picks": sorted(picks.items(), key=lambda x: -x[1]), "by_pick": by_pick,
                     "calls": len(a["items"]), "failed_calls": sum(1 for x in errors if x.get("recipe") == rid),
                     "settings": settings, "requirements": " ".join(str(rt.get("requirements") or "").split()),
                     "by_name": by_model, "place": order.index(rid) + 1,
                     "best_model": recipes.get(best, {}).get("model")})
    return rows


def router_section(rows, agg, order, recipes, best, sec_head):
    if not rows:
        return ""
    out = ["<section id='router'>" + sec_head(
        "Model Router",
        "Recipes with <span class='mono'>model: auto</span> let Runware's Model Router choose the model. It chooses "
        "from the request (schemas, prices, your routing settings, benchmark scores) and does not see the output, "
        "so the same request can get a different model on another call: each seed below is one call. A router "
        "recipe sends one request, so a model that needs other fields than the ones it sends cannot be chosen, "
        "and whatever the request leaves out (size, seed, model settings) is filled in by the router. The checks "
        "are the same ones every other recipe gets.")]
    lines = []
    for x in rows:
        a = agg[x["id"]]
        top, n = x["picks"][0]
        s = (f"<strong>{e(x['id'])}</strong> picked <span class='mono'>{e(short_model(top))}</span> on {n} of "
             f"{x['calls']} calls" + (f" ({len(x['picks'])} different models)" if len(x["picks"]) > 1 else "")
             + f". It stands #{x['place']} of {len(order)}"
             + (f", failing {a['fails']} of {a['checks']} checks" if a["checks"] else "") + ". ")
        if best == x["id"]:
            s += "It is the best recipe against this brief's checks."
        elif x["best_model"] == ROUTER:
            s += f"The best recipe, {e(best)}, is another router recipe."
        else:
            k = dict(x["picks"]).get(x["best_model"], 0)
            s += (f"The best recipe, {e(best)}, calls <span class='mono'>{e(short_model(x['best_model']))}</span>: "
                  + (f"the router chose that model on {k} of {x['calls']} calls." if k
                     else "the router never chose that model."))
        if x["failed_calls"]:
            s += f" {x['failed_calls']} call(s) failed (see Findings)."
        lines.append(note(s))
    out.append(f"<ul class='notes'>{''.join(lines)}</ul>")
    out.append("<div class='tablewrap'><table><thead><tr><th>Router recipe</th><th>Routing settings</th>"
               "<th>Picked</th><th>Calls</th><th title='Failed checks per output, lowest to highest'>Failed checks "
               "per output</th><th>Same model, called by name</th></tr></thead><tbody>")
    for x in rows:
        span = len(x["picks"])
        for i, (m, n) in enumerate(x["picks"]):
            fails = sorted(x["by_pick"][m])
            f_txt = str(fails[0]) if fails[0] == fails[-1] else f"{fails[0]}–{fails[-1]}"
            named = x["by_name"].get(m, [])
            named_txt = "<br>".join(
                f"<button data-id='{e(q)}' class='linkish'>{e(q)}</button> <span class='mono'>#{order.index(q) + 1} · "
                f"{agg[q]['fails']} of {agg[q]['checks']} failed</span>" for q in named) or (
                "<span class='muted'>not in this bench</span>" if m != "not recorded" else "")
            head = ""
            if i == 0:
                req = (f"<div class='strip' title='{e(x['requirements'])}'>requirements: "
                       f"{e(x['requirements'][:80])}{'…' if len(x['requirements']) > 80 else ''}</div>"
                       if x["requirements"] else "")
                head = (f"<td rowspan='{span}'><button data-id='{e(x['id'])}' class='linkish'>{e(x['id'])}</button>"
                        f"<div class='strip'>#{x['place']} of {len(order)}</div></td>"
                        f"<td rowspan='{span}'>{e(' · '.join(x['settings']))}{req}</td>")
            out.append(f"<tr>{head}<td class='mono'>{e(m)}</td><td class='mono'>{n} of {x['calls']}</td>"
                       f"<td class='mono'>{f_txt}</td><td>{named_txt}</td></tr>")
    out.append("</tbody></table></div></section>")
    return "".join(out)


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

    # aggregate per recipe: seeds are judged by `passRule` within each input (one unlucky or lucky seed
    # does not decide), then a recipe must pass a check on every input
    rule = b.get("passRule", b.get("pass_rule", "majority"))
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
    # Standings: failed checks first, then average place on the measurements, then cost. Limits and
    # places both always count; a bench without limits is ordered by place alone.
    cols, direction, placed = place_recipes(b, scored, agg)
    any_checks = any(a["checks"] for a in agg.values())
    order = sorted(agg, key=lambda r: (agg[r]["fails"], agg[r]["place"] if agg[r]["place"] is not None else 1e9,
                                       agg[r]["cost"] if agg[r]["cost"] is not None else 9))
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
            originals[k]["crop"] = uri(rgb_in[box[1]:box[3], box[0]:box[2]], 640, 90)
            originals[k]["crop_name"] = next(iter(boxes))
    for s in scored:
        if s.get("view"):  # 3D output: its rendered front view. Video output: its first frame
            p = Pair(b, inputs[s["input"]], os.path.join(out_dir, s["view"]),
                     os.path.join(out_dir, s["view_mask"]) if s.get("view_mask") else None)
        else:
            f = os.path.join(out_dir, s["file"])
            p = Pair(b, inputs[s["input"]], f, find_mask(out_dir, s["file"], s["recipe"]))
        strip = [f"auto → {s['picked_model']}" if s.get("picked_model") else recipes.get(s["recipe"], {}).get("model", "")]
        if len({x["seed"] for x in scored}) > 1:
            strip.append(f"seed {s['seed']}")
        if s.get("latency_s") is not None:
            strip.append(f"{s['latency_s']:.1f}s")
        if s.get("cost") is not None:
            strip.append(f"${s['cost']:.4f}")
        it = {"img": uri(p.rgb_out, 900), "thumb": uri(p.rgb_out, 360, 80), "gates": gate_rows(s, every=True),
              "strip": " · ".join(x for x in strip if x)}
        try:
            it["heat"] = uri(heatmap(p, first_de), 520)
        except KeyError:
            pass
        box = next(iter(p.boxes.values()), None)
        if box:
            it["crop"] = uri(p.rgb_out[box[1]:box[3], box[0]:box[2]], 640, 90)
        if s.get("turntable") and os.path.exists(os.path.join(out_dir, s["turntable"])):
            it["turn"] = uri(Image.open(os.path.join(out_dir, s["turntable"])).convert("RGB"), 1200, 82)
            it["turn_title"] = s.get("turn_title")
        if s.get("clip") and os.path.exists(os.path.join(out_dir, s["clip"])):
            it["_clip_path"] = os.path.join(out_dir, s["clip"])
        # one output per recipe and input is shown and offered for labeling: the recipe's best seed,
        # i.e. the one that fails the fewest checks (the lowest seed number on a tie)
        key = f"{s['input']}|{s['recipe']}"
        rank = (sum(1 for g in it["gates"] if g["pass"] is False), s["seed"])
        if key not in items or rank < items[key]["_rank"]:
            items[key] = {**it, "_rank": rank, "seed": s["seed"], "file": s["file"], "input": s["input"],
                          "recipe": s["recipe"]}

    # video previews: the first seed of each recipe, embedded while the report stays within the size budget
    clip_bytes, clips_left_out = 0, 0
    for it in items.values():
        path = it.pop("_clip_path", None)
        if not path:
            continue
        size = os.path.getsize(path)
        if clip_bytes + size > CLIP_BUDGET_MB * 1e6:
            clips_left_out += 1
            continue
        clip_bytes += size
        it["clip"] = "data:video/mp4;base64," + base64.b64encode(open(path, "rb").read()).decode()

    title = b.get("title") or "Which recipe works best?"
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>{e(title)}</title>{FONTS}<style>{CSS}{_labeling.CSS}</style></head>"
           f"<body><div class='wrap'>"]
    seeds = sorted({s["seed"] for s in scored})
    best = order[0]
    routed = router_rows(agg, order, recipes, errors, best)
    cheapest_pass = min(passing, key=lambda r: agg[r]["cost"] or 9) if passing else None
    # headline: the recommendation, then what it costs and how many checks it passes.
    # `best` is the first in `order`: fewest failed checks, then best average place, then cheapest
    ab = agg[best]
    price = f" at <em>${ab['cost']:.3f}</em> per output" if ab["cost"] is not None else ""
    missed = [k.split(":", 1)[1] for k, v in ab["verdict"].items() if not v]
    # Three things are kept apart in this report: measured values (the same for everyone), the verdict
    # against this bench's thresholds (a judgement for this brief), and the user's own ranking from the
    # labeling page (their preference). The headline names the second; "Your pick" names the third.
    place_txt = (f"average place {ab['place']:.1f} across the measurements (1.0 = best on all of them)"
                 if ab["place"] is not None else "")
    if not any_checks:
        headline = (f"Best on this brief's measurements: <em>{e(best)}</em>.<br><span class='sub'>"
                    + (f"{place_txt[:1].upper()}{place_txt[1:]}{price}. " if place_txt else f"Measured{price}. " if price else "")
                    + "No pass/fail limits are set.</span>")
    elif passing:
        headline = f"Best against this brief's checks: <em>{e(best)}</em>.<br><span class='sub'>Passes every check{price}.</span>"
    else:
        headline = (f"Best against this brief's checks: <em>{e(best)}</em>.<br><span class='sub'>Passes "
                    f"{ab['checks'] - ab['fails']} of {ab['checks']}{price}.</span>")
    pick_line = "<p class='goal' id='pick-line' hidden></p>"  # filled in by the page from the reader's labels
    controls = data.get("controls", [])
    checks_spend = data.get("judge_cost", 0) + sum(r.get("eval_cost") or 0 for r in data.get("attempted_rows", []))
    goal = " ".join(b["goal"].split())
    task = b.get("task") or re.split(r"(?<=[.!?])\s+", goal, maxsplit=1)[0]  # `task`, else the goal's first sentence
    judges = data.get("judges") or []
    facts = [("Recipes", len(agg), ""), ("Inputs", len(in_order), ", ".join(in_order)),
             ("Seeds", ", ".join(map(str, seeds)), ""), ("Outputs", len(scored), ""),
             ("Generation", f"${measured:.3f}", ""), ("Checks", f"${checks_spend:.3f}", "Spend on judges and paid checks"),
             ("Judges", len(judges) or "off", ", ".join(judges)),
             ("Controls", f"{sum(c['ok'] for c in controls)}/{len(controls)} ok" if controls else "none", "")]
    out.append("<header class='hero'>"
               f"<div class='kicker'><b>runware-eval</b> · bench report · {date.today()}</div>"
               f"<h1>{headline}</h1>{pick_line}<p class='goal' title='{e(goal)}'><strong>Task:</strong> {e(task)}</p>"
               "<dl class='meta'>" + "".join(
                   f"<div{f' title={chr(39)}{e(t)}{chr(39)}' if t else ''}><dt>{k}</dt><dd>{e(str(v))}</dd></div>"
                   for k, v, t in facts) + "</dl></header>")

    def card(label, big, foot, lit=False):
        return (f"<div class='card{' lit' if lit else ''}'><span class='lab'>{label}</span>"
                f"<span class='big'>{big}</span><span class='strip'>{foot}</span></div>")

    if cheapest_pass:
        c = agg[cheapest_pass]
        second = card("Cheapest that passes", f"${c['cost']:.3f}" if c["cost"] is not None else "—",
                      f"{e(cheapest_pass)} · {e(recipes.get(cheapest_pass, {}).get('model', ''))} · {c['cost_src']}")
    elif any_checks:
        second = card("Best still misses", ab["fails"], e(", ".join(missed)))
    elif len(order) > 1 and agg[order[1]]["place"] is not None:
        second = card("Runner-up", f"avg place {agg[order[1]]['place']:.1f}",
                      f"{e(order[1])} · {e(recipes.get(order[1], {}).get('model', ''))}")
    else:
        second = ""
    out.append("<section aria-label='Summary'><div class='cards'>"
               + (card("Best against the checks", f"{ab['checks'] - ab['fails']}/{ab['checks']} checks",
                       f"{e(best)} · {e(recipes.get(best, {}).get('model', ''))}"
                       + (f" · {place_txt}" if place_txt else ""), lit=True) if any_checks else
                  card("Best on the measurements", f"avg place {ab['place']:.1f}" if ab["place"] is not None else "—",
                       f"{e(best)} · {e(recipes.get(best, {}).get('model', ''))} · 1st of {len(agg)} recipes: average "
                       f"of its places on {len(placed)} measurements", lit=True))
               + second
               + "<div class='card lit' id='pick-card' hidden><span class='lab'>Your pick (blind pairs)</span>"
                 "<span class='big' id='pick-big'></span><span class='strip' id='pick-foot'></span></div>"
               + "".join(card("Model Router's pick stands", f"#{x['place']} of {len(order)}",
                              f"{e(x['id'])} · picked {e(short_model(x['picks'][0][0]))} on "
                              f"{x['picks'][0][1]} of {x['calls']} calls")
                         for x in routed[:1])
               + card("Checks not run", len(not_run), e(", ".join(not_run)) or "all ran")
               + card("Failed tasks", len(errors), e(", ".join(sorted({x["recipe"] for x in errors}))) or "none")
               + "</div></section>")

    sec_n = [0]

    def sec_head(h2, intro=""):
        sec_n[0] += 1
        return (f"<div class='sec-head'><h2><span class='num'>{sec_n[0]:02d}</span>{h2}</h2>"
                + (f"<p class='ink2'>{intro}</p>" if intro else "") + "</div>")

    bad_ctl = [c for c in data.get("controls", []) if not c["ok"]]
    full = max(len(a["items"]) for a in agg.values())
    partial = [f"{rid} ({len(a['items'])} of {full})" for rid, a in agg.items() if len(a["items"]) < full]
    if notes.get("findings") or notes.get("caveats") or missing or errors or bad_ctl or partial:
        rows = [note(*split_note(n)) for n in notes.get("findings", [])]
        warns = [note(*split_note(n), warn=True) for n in notes.get("caveats", [])]
        for c in bad_ctl:
            warns.append(note(f"<strong>Control failed:</strong> {e(c['label'])}",
                              f"On an unchanged copy of {e(c['input'])}: {fmtv(c['value'])}, "
                              f"{'failed' if c['expected_pass'] else 'passed'} (expected "
                              f"{'pass' if c['expected_pass'] else 'fail'}). Check or threshold does not fit this bench.", True))
        failed = {}  # the same failure on several seeds is one line
        for x in errors:
            failed.setdefault((x["recipe"], x["input"], str(x.get("error"))), []).append(x)
        for (rid, inp, err), xs in failed.items():
            warns.append(note(f"<strong>{e(rid)}</strong> failed on {e(inp)}" + (f" ({len(xs)} times)" if len(xs) > 1 else ""),
                              e(err), True))
        if partial:
            warns.append(note("<strong>Fewer outputs than the other recipes</strong>",
                              f"{e(', '.join(partial))}. Their verdicts rest on less evidence.", True))
        if missing:
            warns.append(note(f"<strong>No output in this folder:</strong> {e(', '.join(missing))}", warn=True))
        out.append("<section>" + sec_head("Findings") + "".join(
            f"<details class='fold'{' open' if w == 'findings' else ''}><summary>{len(x)} {w}<span class='muted'> · "
            f"click a line for its detail</span></summary><ul class='notes'>{''.join(x)}</ul></details>"
            for x, w in ((rows, "findings"), (warns, "caveats")) if x) + "</section>")

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
            def better(lab, gate):  # the measurement's own direction, else the side its limit sits on
                d = next((v for k, v in direction.items() if k.split(":", 1)[1] == lab), "")
                return BETTER.get(d) or (BETTER["higher" if gate[1] == "min" else "lower"] if gate else "")
            xgate, ygate = gate_of(scored, xlab) if xlab != "cost" else None, gate_of(scored, ylab)
            out.append("<section>" + sec_head(
                ("Cost" if xlab == "cost" else e(xlab)) + f" vs {e(ylab)}",
                "Mean across inputs. " + ("Dashed: this brief's limits. Green: within the limits shown here. "
                                          "Orange: outside them." if xgate or ygate else "Filled: no failed check."))
                       + scatter(pts, "Cost per output (USD)" if xlab == "cost" else xlab, ylab,
                                 BETTER["lower"] if xlab == "cost" else better(xlab, xgate), better(ylab, ygate),
                                 xgate, ygate) + "</section>")

    # what the brief asks, and what measures it
    cov, _ = coverage(b)
    if cov:
        chip = {"limit": "<span class='chip ok'>measured, with a limit</span>",
                "measured": "<span class='chip na'>measured, no limit</span>",
                "none": "<span class='chip bad'>not measured</span>"}
        holes = sum(1 for r in cov if r["status"] != "limit")
        out.append("<section>" + sec_head(
            "What the brief asks",
            "Each requirement of the brief and the checks that answer it. "
            + (f"<strong>{holes} of {len(cov)} cannot fail a recipe</strong>: the standings do not reflect "
               "them fully, so judge those by eye." if holes else "Every requirement has a check with a limit."))
            + "<div class='tablewrap'><table><thead><tr><th>Requirement</th><th>Measured by</th><th></th></tr></thead><tbody>"
            + "".join(f"<tr><td>{e(r['need'])}</td><td>"
                      + (e(", ".join(c["label"] + ("" if c["known"] else " (missing)") for c in r["checks"])) or "—")
                      + f"</td><td>{chip[r['status']]}</td></tr>" for r in cov)
            + "</tbody></table></div></section>")

    # standings: every measurement, with its verdict where a limit is set
    rule_txt = {"majority": "most seeds", "all": "every seed", "any": "at least one seed"}.get(rule, rule)
    groups = []
    for c in cols:
        if not groups or groups[-1][0] != c["dimension"]:
            groups.append([c["dimension"], 0])
        groups[-1][1] += 1
    arrow = {"lower": " ↓", "higher": " ↑", "closer_to_zero": " →0"}
    unplaced = [c["label"] for c in cols if c["key"] not in placed]
    out.append("<section>" + sec_head(
               "Standings",
               "Every measurement counts. Recipes are sorted by <strong>failed checks</strong> (a measurement with a "
               "limit in <span class='mono'>bench.yaml</span>: this brief's judgement, which can be changed), then by "
               "<strong>average place</strong> (place 1 = best on a measurement; places are averaged inside each "
               "dimension, then across dimensions, so a dimension counts once however many measurements it has), "
               "then by cost. "
               + (f"A check passes when it passes on {rule_txt} of every input (<span class='mono'>passRule: {e(rule)}"
                  "</span>). " if any_checks else "This bench sets no limits, so nothing passes or fails here. ")
               + "Cells: mean over inputs and seeds; ↑ higher is better, ↓ lower is better; bold = best in the column."
               + (f" Not placed (not measured for every recipe, or no better direction): {e(', '.join(unplaced))}."
                  if unplaced else ""))
               + "<div class='tablewrap'><table><thead><tr><th></th><th></th><th></th><th></th>"
               + "".join(f"<th class='grp' colspan='{n}'>{e(d.replace('_', ' '))}</th>" for d, n in groups)
               + "<th></th><th></th></tr><tr><th>#</th><th>Recipe</th><th>Failed</th><th title='Average of this recipe&#39;s places on the measurements; 1.0 = best on all of them'>Average place</th>"
               + "".join(f"<th>{e(c['label'])}{arrow.get(direction.get(c['key']), '')}</th>" for c in cols)
               + "<th title='USD per output'>Cost</th><th title='Seconds from request to result'>Speed</th></tr></thead><tbody>")
    model_txt = {x["id"]: "auto → " + ", ".join(f"{short_model(m)} ×{n}" for m, n in x["picks"]) for x in routed}
    for n, rid in enumerate(order, 1):
        a, cells = agg[rid], []
        for c in cols:
            k = c["key"]
            mean = a["means"].get(k)
            if mean is None:
                cells.append("<td><span class='chip na'>not run</span></td>")
                continue
            lead = k in placed and a["places"][k] == min(agg[r]["places"][k] for r in agg)
            val = f"<span class='mono'{' style=\'font-weight:700\'' if lead else ''}>{fmtv(mean)}</span>"
            if k in a["verdict"]:
                ok = [p for by_in in a["by_check"][k].values() for p in by_in]
                v = a["verdict"][k]
                cells.append(f"<td><span class='chip {'ok' if v else 'bad'}' title='passed on {sum(ok)} of {len(ok)} "
                             f"outputs (inputs x seeds)'>{'✓' if v else '✕'} {val}"
                             + (f" <span class='mono'>· {sum(ok)}/{len(ok)}</span>" if len(ok) > 1 else "")
                             + "</span></td>")
            else:
                title = f" title='place {a['places'][k]:g} of {len(agg)}'" if k in placed else ""
                cells.append(f"<td{title}>{val}</td>")
        cost = f"${a['cost']:.4f}" + ("" if a["cost_src"] == "measured" else "*") if a["cost"] is not None else "—"
        lat = f"{a['latency']:.0f}s" if a["latency"] else "—"
        failed = f"{a['fails']} of {a['checks']}" if a["checks"] else "—"
        by_dim = " · ".join(f"{d.replace('_', ' ')} {p:.1f}" for d, p in a["place_by_dim"].items())
        place = f"<span title='{e(by_dim)}'>{a['place']:.1f}</span>" if a["place"] is not None else "—"
        out.append(f"<tr><td class='rank'>{n}</td><td><button data-id='{e(rid)}' class='linkish'>{e(rid)}</button><div class='strip'>"
                   f"{e(model_txt.get(rid) or recipes.get(rid, {}).get('model', ''))} · {e(recipes.get(rid, {}).get('_fp', '') or '')[:8]}</div></td>"
                   f"<td class='mono'>{failed}</td><td class='mono'>{place}</td>{''.join(cells)}"
                   f"<td class='mono'>{cost}</td><td class='mono'>{lat}</td></tr>")
    out.append("</tbody></table></div><p class='muted' style='font-size:12px'>* listed price, not measured.</p></section>")
    out.append(router_section(routed, agg, order, recipes, best, sec_head))

    # comparison viewer
    crop_name = next((o.get("crop_name") for o in originals.values() if o.get("crop_name")), None)
    out.append("<section id='compare'>" + sec_head("Output vs original", "Shown per recipe: its best seed, the one that fails the fewest checks."
                                               if len(seeds) > 1 else ""))
    if len(in_order) > 1:
        out.append("<div class='picker' role='group' aria-label='Input'>" + "".join(
            f"<button data-in='{e(k)}' aria-pressed='false'>{e(k)}</button>" for k in in_order) + "</div>")
    out.append("<div class='picker' role='group' aria-label='Recipe'>" + "".join(
        f"<button data-id='{e(r)}' aria-pressed='false'>{e(r)}<span class='n'>{agg[r]['fails']}✕</span></button>"
        for r in order) + "</div><div class='split'><div style='display:grid;gap:6px'>"
        "<div class='ba' aria-label='Drag to compare original and output'><img class='before' alt='Original'>"
        "<div class='after'><img alt='Output'></div><div class='bar'></div><div class='knob'>⇆</div>"
        "<span class='tag l'>original</span><span class='tag r'></span></div><span class='muted' "
        "style='font-size:12px'>Drag, or use ← → when focused.</span></div>"
        f"<div class='panel'><h3>{'Checks and measurements' if any_checks else 'Measurements'}</h3>"
        "<dl class='kv' id='kv'></dl></div></div>"
        # everything else sits in a row under the slider, as wide as the page
        "<div class='below'><div class='panel'><h3>Where the colour changed</h3><img id='heat' alt='Colour drift heatmap'>"
        "<div class='legend-bar'></div><div class='legend-ticks'><span>0 ΔE (unchanged)</span><span>"
        f"{HEAT_MAX / 2:.0f}</span><span>{HEAT_MAX:.0f}+ ΔE</span></div><p class='muted' style='font-size:12px'>"
        f"Same settings as the first colour check{' (hue and chroma only)' if first_de.get('ignore_lightness') else ''}."
        "</p></div>")
    if crop_name:
        out.append(f"<div class='panel'><h3>{e(crop_name.capitalize())}</h3><div class='ba' aria-label='Drag to compare "
                   "the original and output crop'><img class='before' id='crop-in' alt='Original crop'>"
                   "<div class='after'><img id='crop-out' alt='Output crop'></div><div class='bar'></div>"
                   "<div class='knob'>⇆</div><span class='tag l'>original</span>"
                   "<span class='tag r' id='crop-out-cap'></span></div></div>")
    out.append("<div class='panel' id='clip-panel' hidden><h3>Clip</h3><video id='clip' controls loop muted "
               "playsinline style='width:100%;border-radius:var(--r)'></video>"
               + (f"<p class='muted' style='font-size:12px'>{clips_left_out} more clip(s) are in the run folder "
                  "(left out to keep this file small).</p>" if clips_left_out else "") + "</div>")
    out.append("<div class='panel wide' id='turn-panel' hidden><h3 id='turn-title'>Views</h3>"
               "<img id='turn' alt='Views of the output'></div></div></section>")

    # gallery
    out.append("<section>" + sec_head("Outputs", ("Each recipe's best seed (the one that fails the fewest checks): model · seed · speed · cost. "
                                               if len(seeds) > 1 else "Model · speed · cost. ") + "Click to compare."))
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

    # labeling, agreement with the checks and the reader's own ranking: all computed in the page
    initial = {}
    labels_path = os.path.join(out_dir, "labels.json")
    if os.path.exists(labels_path):  # labels given to `runware-eval calibrate` travel with the report
        initial = json.load(open(labels_path, encoding="utf8"))
    cal_data, lab_data = _labeling.data(scored, items, title, os.path.basename(out_dir.rstrip("/\\")),
                                        {"labels": initial.get("labels", {}), "pairs": initial.get("pairs", [])})
    out.append("<section id='labels'>" + sec_head("Your labels") + _labeling.section(len(lab_data["pairs"])) + "</section>")

    # full data
    labels = []
    for s in scored:
        for m in s["metrics"]:
            if m["label"] not in labels:
                labels.append(m["label"])
    out.append("<section>" + sec_head("All measurements", "The measured values, before any threshold: the same "
                                      "for every user and every re-run of the same outputs.") + "<details><summary>Show table</summary><div class='tablewrap' "
               "style='margin-top:12px'><table><thead><tr><th>Input</th><th>Recipe</th><th>Seed</th><th>Native</th>"
               "<th>Cost</th><th title='Seconds from request to result'>Speed</th>" + "".join(f"<th>{e(l)}</th>" for l in labels) + "</tr></thead><tbody>")
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

    payload = {"inputs": in_order, "order": order, "originals": originals, "cal": cal_data, "lab": lab_data, "best": best,
               "recipes": {r: {"checks": a["checks"], "fails": a["fails"], "cost": a["cost"], "place": a["place"],
                               "model": recipes.get(r, {}).get("model", "")} for r, a in agg.items()},
               "items": {k: {kk: vv for kk, vv in v.items() if kk not in ("thumb", "_rank", "strip")} for k, v in items.items()}}
    out.append(f"<div class='tip' role='tooltip'></div><script type='application/json' id='data'>{json.dumps(payload)}"
               f"</script><script>{JS}{_labeling.JS}</script></div></body></html>")
    out_path = out_path or os.path.join(out_dir, "report.html")
    open(out_path, "w", encoding="utf8").write("".join(out))
    return out_path
