"""Score outputs against the `evaluate` block of bench.yaml. Writes scores.json.

Each metric returns named values; gates compare them with the thresholds written next to the
metric in bench.yaml (min, max, mean_max, p95_max, max_px, aspect_tolerance, abs_max, or a
legacy `rule: "... >= 3"`). Metrics not implemented yet are reported as `not_run`, never as passes.
"""
import glob
import json
import os
import re

import cv2
import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from concurrent.futures import ThreadPoolExecutor

from . import catalog
from . import judge as judge_mod
from .metric_api import erode  # noqa: F401  (re-exported for report.py and judge.py)
from . import render as render_mod
from .bench import stem


# ---------- loading ----------

def load_rgb(path, size=None):
    im = Image.open(path).convert("RGB")
    native = im.size
    if size and im.size != size:
        im = im.resize(size, Image.BICUBIC)
    return np.asarray(im).astype(np.float64) / 255.0, native


def load_mask(path, size):
    im = Image.open(path)
    a = im.split()[-1] if im.mode in ("RGBA", "LA") else im.convert("L")
    if a.size != size:
        a = a.resize(size, Image.BILINEAR)
    return np.asarray(a) > 127




def input_region(b, inp, spec):
    """A named region of an input, at the input's size: a mask file, a `box`, or `not(<region>)`."""
    W, H = Image.open(os.path.join(b["_dir"], inp["path"])).size
    m = re.fullmatch(r"not\((\w+)\)", spec)
    if m:
        return ~input_region(b, inp, m.group(1))
    v = (inp.get("regions") or {}).get(spec)
    if isinstance(v, dict) and "box" in v:
        x0, y0, x1, y1 = v["box"]
        r = np.zeros((H, W), bool)
        r[y0:y1, x0:x1] = True
        return r
    if isinstance(v, str) and not v.startswith("auto:"):
        return load_mask(os.path.join(b["_dir"], v), (W, H))
    raise KeyError(f"Region '{spec}' is not defined for {inp['path']}")


class Pair:
    """An input and one output, aligned to the input's size, with cached derived data."""

    def __init__(self, b, inp, out_path, out_mask_path):
        self.src = os.path.join(b["_dir"], inp["path"])
        self.rgb_in, (self.W, self.H) = load_rgb(self.src)
        self.rgb_out, self.native = load_rgb(out_path, (self.W, self.H))
        self.lab_in, self.lab_out = rgb2lab(self.rgb_in), rgb2lab(self.rgb_out)
        regions = inp.get("regions") or {}
        self.boxes = {k: v["box"] for k, v in regions.items() if isinstance(v, dict) and "box" in v}
        self.masks_in = {k: load_mask(os.path.join(b["_dir"], v), (self.W, self.H))
                         for k, v in regions.items() if isinstance(v, str) and not v.startswith("auto:")}
        self.m_out = load_mask(out_mask_path, (self.W, self.H)) if out_mask_path else None

    def region(self, spec, side="in"):
        """`product`, `not(product)`, a box region, or None for the whole frame."""
        if spec is None:
            return np.ones((self.H, self.W), bool)
        m = re.fullmatch(r"not\((\w+)\)", spec)
        if m:
            return ~self.region(m.group(1), side)
        if spec in self.boxes:
            x0, y0, x1, y1 = self.boxes[spec]
            r = np.zeros((self.H, self.W), bool)
            r[y0:y1, x0:x1] = True
            return r
        if spec not in self.masks_in:
            raise KeyError(f"Region '{spec}' is not defined for {self.src}")
        if side == "out" and spec == "product" and self.m_out is not None:
            return self.m_out
        return self.masks_in[spec]


# ---------- metrics ----------
# Implementations live in one file each: the curated library (runware_eval/metrics_lib/) plus a
# bench's own metrics/ folder and any shared metric_dirs. See catalog.py and metric_api.py.


def copied_regions(recipe):
    """Regions a recipe copies from the original in a post step: pixel similarity there is by construction."""
    return {list(s.values())[0] for s in (recipe or {}).get("post") or []
            if any(k in s for k in ("restore", "transfer_detail"))}
# ---------- gates ----------

def check(vals, opt):
    """True/False against the thresholds next to the metric; None if no threshold was given."""
    v, tests = vals.get("value"), []
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    for k, fn in (("min", lambda t: v >= t), ("max", lambda t: v <= t), ("max_px", lambda t: v <= t),
                  ("aspect_tolerance", lambda t: v <= t), ("abs_max", lambda t: abs(v) <= t),
                  ("mean_max", lambda t: vals.get("mean", v) <= t), ("p95_max", lambda t: vals.get("p95", v) <= t),
                  ("dL_min", lambda t: v >= t), ("dL_max", lambda t: v <= t)):
        if k in opt:
            tests.append(fn(opt[k]))
    m = re.search(r"(>=|<=)\s*(-?[\d.]+)\s*$", str(opt.get("rule", "")))
    if m:
        tests.append(v >= float(m.group(2)) if m.group(1) == ">=" else v <= float(m.group(2)))
    return all(tests) if tests else None


NAMES = {
    "size_aspect": "Aspect", "phase_correlation": "Shift", "mask_iou": "Outline", "deltaE2000_region": "Colour",
    "ssim_region": "Structure", "sharpness_laplacian": "Sharpness", "lr_lighting_shift": "Key light",
    "shading_contrast": "Contrast", "backdrop_lightness": "Backdrop light", "contact_shadow": "Contact shadow",
    "ocr_cer": "Text", "ocr_extra_text": "Extra text", "vlm_checklist": "Judge checklist", "vlm_rubric": "Judge rubric",
    "vlm_same_object": "Same object", "pairwise_human": "Human ranking", "dino_similarity": "Identity",
}
REGION_NAMES = {"product": "", "not(product)": "backdrop"}


def label(opt):
    """Readable column name. `label:` in bench.yaml wins; otherwise metric name plus region."""
    if opt.get("label"):
        return opt["label"]
    key = opt.get("name") or opt["id"]
    name = NAMES.get(key, key.replace("_", " ").capitalize())
    region = opt.get("region")
    region = REGION_NAMES.get(region, region) if region else ""
    return f"{name} ({region})" if region else name


JUDGED = ("vlm_checklist", "vlm_same_object", "vlm_rubric")


def metric_id(opt):
    """`task_specific` + `name` is the older spelling of a metric id; both work."""
    return opt.get("name") if opt["id"] == "task_specific" else opt["id"]


def score_pair(b, p, pending=None, recipe=None, reg=None):
    """Deterministic metrics now; vision-model metrics are queued in `pending` (run later, in parallel)."""
    rows = []
    copied = copied_regions(recipe)
    reg = reg if reg is not None else catalog.load(b)
    for dim, spec in (b.get("evaluate") or {}).items():
        for opt in spec.get("metrics", []):
            row = {"dimension": dim, "mode": spec.get("mode", "gate"), "id": opt["id"], "label": label(opt),
                   "thresholds": {k: v for k, v in opt.items() if k not in (
                       "id", "name", "label", "region", "rule", "on", "judges", "questions", "rubric", "scale")}}
            if opt["id"] in JUDGED:
                if pending is None:
                    rows.append({**row, "status": "not_run", "note": "vision judges switched off"})
                else:
                    row = {**row, "status": "pending"}
                    rows.append(row)
                    pending.append((row, p, opt))
                continue
            m = reg.get(metric_id(opt))
            if m is None:
                rows.append({**row, "status": "not_run",
                             "note": f"no metric file '{metric_id(opt)}' in the library or the bench's metrics/"})
                continue
            fn = m["compute"]
            row.update(metric_fp=m["fp"], metric_source=m["source"])
            if m["meta"].get("copy_sensitive") and opt.get("region") in copied:
                rows.append({**row, "status": "not_run",
                             "note": f"copied from the original by this recipe: a pass would be by construction"})
                continue
            try:
                vals = fn(p, opt)
                rows.append({**row, "status": "ok", "values": vals,
                             "pass": check(vals, opt) if row["mode"] == "gate" else None})
            except (KeyError, ValueError, IndexError) as e:
                rows.append({**row, "status": "error", "note": str(e)})
    return rows


def controls(b, reg):
    """Score each input against an unchanged copy of itself. A `preserve` gate must pass, a `change`
    gate must fail. A control that goes the wrong way means the check or its threshold is broken."""
    out = []
    for inp in b["inputs"]:
        src = os.path.join(b["_dir"], inp["path"])
        prod = (inp.get("regions") or {}).get("product")
        mask = os.path.join(b["_dir"], prod) if isinstance(prod, str) and not prod.startswith("auto:") else None
        p = Pair(b, inp, src, mask)
        for dim, spec in (b.get("evaluate") or {}).items():
            if spec.get("mode", "gate") != "gate":
                continue
            for opt in spec.get("metrics", []):
                m = reg.get(metric_id(opt))
                if m is None or opt["id"] in JUDGED or m["meta"].get("kind") not in ("preserve", "change"):
                    continue
                try:
                    vals = m["compute"](p, opt)
                except (KeyError, ValueError, IndexError):
                    continue
                passed = check(vals, opt)
                if passed is None:
                    continue
                expected = m["meta"]["kind"] == "preserve"
                out.append({"input": stem(inp["path"]), "dimension": dim, "label": label(opt),
                            "kind": m["meta"]["kind"], "value": vals.get("value"), "passed": passed,
                            "expected_pass": expected, "ok": passed == expected})
    return out


def find_mask(out_dir, fname, recipe):
    for c in (os.path.join(out_dir, "masks", fname.rsplit(".", 1)[0] + "_cut.png"),
              os.path.join(out_dir, "masks", f"{recipe}_cut.png")):
        if os.path.exists(c):
            return c
    return None


def judge_calls(b):
    """Vision-model calls one judged output needs: one combined call per image set, per judge."""
    sets = {o.get("region") for spec in (b.get("evaluate") or {}).values() for o in spec.get("metrics", [])
            if o["id"] in JUDGED}
    return len(sets) * len(b.get("judges") or judge_mod.DEFAULT_JUDGES)


def pixel_fails(metrics):
    return sum(1 for m in metrics if m["mode"] == "gate" and m["id"] not in JUDGED and m.get("pass") is False)


OUT_RE = re.compile(r"(.+?)__(.+?)__s(\d+)\.\w+$")


def score_all(b, out_dir, results=None, judges=True, max_usd=None, log=print):
    """Score every output file in out_dir. Uses results.jsonl for cost and latency when present."""
    ops = {r["file"]: r for r in (results or []) if r.get("status") == "success" and r.get("file")}
    inputs = {stem(i["path"]): i for i in b["inputs"]}
    files = [f for f in sorted(glob.glob(os.path.join(out_dir, "*__*__s*.*")))
             if OUT_RE.match(os.path.basename(f)) and os.path.basename(f).split("__")[0] in inputs]
    reg = catalog.load(b)
    ctl = controls(b, reg)
    bad = [c for c in ctl if not c["ok"]]
    log(f"Controls: {len(ctl) - len(bad)}/{len(ctl)} as expected on unchanged inputs"
        + (f"; CHECK THESE: {', '.join(sorted({c['label'] for c in bad}))}" if bad else "."))
    panel = judge_mod.Panel(b.get("judges"), out_dir, log) if judges else None
    max_failed = (b.get("judge_when") or {}).get("max_failed_checks", 1)
    recipes_by_id = {r["id"]: r for r in b.get("recipes") or [] if isinstance(r, dict)}
    scored, pending = [], []
    for f in files:
        fname = os.path.basename(f)
        inp, recipe, seed = OUT_RE.match(fname).groups()
        view = None
        if render_mod.is_mesh(f):
            # render adapter: the mesh becomes a front view on the input's canvas, so image checks apply
            os.makedirs(os.path.join(out_dir, "renders"), exist_ok=True)
            stem_ = fname.rsplit(".", 1)[0]
            vpng = os.path.join(out_dir, "renders", stem_ + "__front.png")
            vmask = os.path.join(out_dir, "renders", stem_ + "__front_cut.png")
            vjson = os.path.join(out_dir, "renders", stem_ + "__view.json")
            if not os.path.exists(vjson):
                ip = inputs[inp]
                src = os.path.join(b["_dir"], ip["path"])
                rgb = np.asarray(Image.open(src).convert("RGB"))
                tm = input_region(b, ip, "product")
                bg = np.median(rgb[~tm], axis=0) if (~tm).any() else (255, 255, 255)
                log(f"  rendering {fname}: searching the view that matches the photo ...")
                info = render_mod.front_view(f, tm, bg, vpng, vmask)
                info["mesh"] = render_mod.mesh_facts(f)
                render_mod.turntable(f, os.path.join(out_dir, "renders", stem_ + "__turntable.jpg"))
                json.dump(info, open(vjson, "w"))
            view = json.load(open(vjson))
            p = Pair(b, inputs[inp], vpng, vmask)
            p.mesh = view["mesh"]
        else:
            p = Pair(b, inputs[inp], f, find_mask(out_dir, fname, recipe))
        jobs = [] if panel else None
        metrics = score_pair(b, p, jobs, recipes_by_id.get(recipe), reg)
        fails = pixel_fails(metrics)
        group = {}
        for row, pair, opt in jobs or []:
            if fails > max_failed:
                row.update(status="not_run", note=f"skipped: failed {fails} pixel checks")
                continue
            # one combined call per output and image set; keep only small inline images while queued
            g = group.setdefault(opt.get("region"), {"items": [], "refs": []})
            g["items"].append((row, opt))
            g["refs"] += [x for x in opt.get("refs") or [] if x not in g["refs"]]
            g["pair"] = pair
        for region, g in group.items():
            prepared = judge_mod.prepare(g["pair"], {"region": region, "refs": g["refs"]}, b)
            pending.append((g["items"], prepared))
        r = ops.get(fname, {})
        entry = {"input": inp, "recipe": recipe, "seed": int(seed), "file": fname,
                 "native": f"{p.native[0]}x{p.native[1]}", "cost": r.get("cost"),
                 "latency_s": r.get("latency_s"), "metrics": metrics}
        if view:
            stem_ = fname.rsplit(".", 1)[0]
            entry.update(view=f"renders/{stem_}__front.png", view_mask=f"renders/{stem_}__front_cut.png",
                         turntable=f"renders/{stem_}__turntable.jpg", view_info=view,
                         native=f"{view['mesh']['faces']:,} faces")
        scored.append(entry)
    if pending:
        # budget check after the pixel funnel: only outputs that will actually be judged count
        calls = len(pending) * len(panel.judges)
        projected = calls * judge_mod.EST_COST_PER_CALL
        spent = sum((r.get("spend", r.get("cost")) or 0) + (r.get("eval_cost") or 0)
                    for r in (results or []) if not r.get("reused_from"))
        log(f"Vision judges: {len(pending)} output(s) passed the pixel funnel (at most {max_failed} failed "
            f"check(s)); up to {calls} calls, about ${projected:.2f} (cached answers are free).")
        if max_usd is not None and spent + projected > max_usd:
            log(f"Skipping vision judges: ${spent + projected:.2f} would exceed the ${max_usd:.2f} cap.")
            for items, _ in pending:
                for row, _ in items:
                    row.update(status="not_run", note="skipped: budget cap")
            pending = []
    if pending:
        def one(item):
            items, prepared = item
            try:
                results_ = judge_mod.run_combined(panel, prepared, [opt for _, opt in items])
                for (row, opt), vals in zip(items, results_):
                    ok = not (isinstance(vals.get("value"), float) and np.isnan(vals["value"]))
                    row.update(status="ok" if ok else "error", values=vals, note=vals.get("note"))
                    row["pass"] = check(vals, opt) if row["mode"] == "gate" and ok else None
            except Exception as e:  # one judge failure must not sink the whole report
                for row, _ in items:
                    row.update(status="error", note=str(e))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, pending))
        log(f"Vision judges done: ${panel.spent:.3f} spent on new answers.")
    errors = [r for r in (results or []) if r.get("status") == "error"]
    attempted = [{"recipe": r["recipe"], "input": r["input"]} for r in (results or [])]
    data = {"scored": scored, "errors": errors, "attempted": attempted, "controls": ctl,
            "metrics": {mid: {"fp": m["fp"], "source": m["source"]} for mid, m in reg.items()},
            "attempted_rows": [{"eval_cost": r.get("eval_cost")} for r in (results or [])],
            "judges": panel.judges if panel else [], "judge_cost": judge_mod.total_cost(out_dir)}
    json.dump(data, open(os.path.join(out_dir, "scores.json"), "w", encoding="utf8"), indent=1)
    return data
