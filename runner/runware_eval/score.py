"""Score outputs against the `evaluate` block of bench.yaml. Writes scores.json.

Each metric returns named values; a check compares them with the limits written next to the metric
in bench.yaml or frozen in limits.yaml (min, max, mean_max, p95_max, max_px, aspect_tolerance, abs_max).
A metric id with no file behind it is reported as `not_run`, never as a pass.
"""
import glob
import hashlib
import json
import os
import re

import numpy as np
from PIL import Image
from skimage.color import rgb2lab

from concurrent.futures import ThreadPoolExecutor

from . import adapters, catalog
from . import judge as judge_mod
from . import text as textmod
from .metric_api import erode  # noqa: F401  (re-exported for report.py and judge.py)
from . import render as render_mod
from . import video as video_mod
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
    if isinstance(v, str) and not v.startswith(("auto:", "detect:")):
        return load_mask(os.path.join(b["_dir"], v), (W, H))
    raise KeyError(f"Region '{spec}' is not defined for {inp['path']}")


def input_rgb(b, inp):
    """An input as a picture: the image itself, or a text input drawn on a card. Returns (rgb, size)."""
    src = os.path.join(b["_dir"], inp["path"])
    if textmod.is_text(src):
        card = textmod.card(textmod.read(src))
        return np.asarray(card).astype(np.float64) / 255.0, card.size
    return load_rgb(src)


class Pair:
    """An input and one output, aligned to the input's size, with cached derived data.

    `out_path` is the picture of the output: the file itself for an image, or what an adapter made of
    it (a render, a first frame, a card). `out_file` is always the file as delivered."""

    def __init__(self, b, inp, out_path, out_mask_path):
        self.src = os.path.join(b["_dir"], inp["path"])
        self.bench, self.input = b, inp
        self.text_in = textmod.read(self.src) if textmod.is_text(self.src) else None
        self.rgb_in, (self.W, self.H) = input_rgb(b, inp)
        self.out_file = out_path
        self.rgb_out, self.native = load_rgb(out_path, (self.W, self.H))
        self.lab_in, self.lab_out = rgb2lab(self.rgb_in), rgb2lab(self.rgb_out)
        regions = inp.get("regions") or {}
        self.boxes = {k: v["box"] for k, v in regions.items() if isinstance(v, dict) and "box" in v}
        self.masks_in = {k: load_mask(os.path.join(b["_dir"], v), (self.W, self.H))
                         for k, v in regions.items() if isinstance(v, str) and not v.startswith(("auto:", "detect:"))}
        self.m_out = load_mask(out_mask_path, (self.W, self.H)) if out_mask_path else None
        self.mesh = self.video = self.svg = self.text = None
        self.text_meta, self.alpha_file, self.no_picture = {}, None, None
        self.out_is_outline = False  # a cut-out or a mask: the output is an outline, whatever the region is called

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
        if side == "out" and self.m_out is not None and (spec == "product" or self.out_is_outline):
            return self.m_out
        return self.masks_in[spec]


# ---------- metrics ----------
# Implementations live in one file each: the curated library (runware_eval/metrics_lib/) plus a
# bench's own metrics/ folder and any shared metricDirs. See catalog.py and metric_api.py.


def copied_regions(recipe):
    """Regions a recipe copies from the original in a post step: pixel similarity there is by construction."""
    return {list(s.values())[0] for s in (recipe or {}).get("post") or []
            if any(k in s for k in ("restore", "transferDetail"))}
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
    if not tests and opt.get("id") in YES_NO and isinstance(vals.get("yes"), bool):
        return vals["yes"]  # a yes/no question is its own limit: yes passes
    return all(tests) if tests else None


YES_NO = ("vlm_checklist", "vlm_same_object")  # judge checks that answer yes or no: pass/fail without a number
LIMIT_KEYS = ("min", "max", "max_px", "aspect_tolerance", "abs_max", "mean_max", "p95_max", "dL_min", "dL_max")


def row_mode(opt):
    """A measurement with a limit next to it is a pass/fail check ("gate"); without one it only places
    the recipes ("rank"). Nobody has to choose: the report uses both."""
    return "gate" if any(k in opt for k in LIMIT_KEYS) or opt.get("id") in YES_NO else "rank"


NOT_LIMITS = ("id", "label", "region", "on", "judges", "questions", "rubric", "scale", "terms", "banned", "keys",
              "pattern", "case", "field", "strict", "min_share", "edge_pct", "limit", "limitFrom", "text", "min_conf", "kind")


def thresholds(opt):
    """What a row records of its check: the limits and the metric's own options."""
    return {k: v for k, v in opt.items() if k not in NOT_LIMITS}


def all_checks(b):
    """Every check of the bench: (dimension, its entry in `evaluate`)."""
    return [(dim, opt) for dim, spec in (b.get("evaluate") or {}).items() for opt in spec.get("metrics", [])]


def coverage(b):
    """`requirements` in bench.yaml lists what the brief asks, each with the labels of the checks that
    measure it. Returns (rows, warnings): a requirement nothing measures, or that has no limit, is a
    hole a recipe can fall through unnoticed. A requirement the user chose to leave out says so
    (`notMeasured: <why>`) and is listed as such; `coverage_errors` names the holes that stop a run."""
    limits = {}
    for _, opt in all_checks(b):
        limits[label(opt)] = row_mode(opt) == "gate"
    rows, warn = [], []
    reqs = b.get("requirements") or []
    if not reqs:
        warn.append("bench.yaml has no `requirements`: nothing shows which part of the brief each check covers.")
    for r in reqs:
        need = r.get("need", "") if isinstance(r, dict) else str(r)
        names = (r.get("checks") or []) if isinstance(r, dict) else []
        checks = [{"label": n, "known": n in limits, "limit": limits.get(n, False)} for n in names]
        known = [c for c in checks if c["known"]]
        why = r.get("notMeasured") if isinstance(r, dict) else None
        status = "limit" if any(c["limit"] for c in known) else "measured" if known else "dropped" if why else "none"
        rows.append({"need": need, "checks": checks, "status": status, "why": why if status == "dropped" else None})
        for c in checks:
            if not c["known"]:
                warn.append(f"requirement '{need}' names a check that is not in `evaluate`: {c['label']}")
        if status == "none":
            warn.append(f"nothing measures: {need}")
        elif status == "dropped":
            warn.append(f"left out by choice ({why}): {need}")
        elif status == "measured":
            warn.append(f"measured, no limit yet (numeric checks get theirs from the first full run): {need}")
    if limits and not any(limits.values()):
        warn.append("no check has a limit: recipes can only be placed, none can fail.")
    used = {c["label"] for r in rows for c in r["checks"]}
    if reqs:
        for n in limits:
            if n not in used:
                warn.append(f"check '{n}' is not tied to any requirement")
    return rows, warn


def coverage_errors(b):
    """Holes that are a mistake in the bench, not a choice: a requirement with no check (every
    requirement gets a metric, written for it if the library has none), and a requirement that names a
    check `evaluate` does not have. A paid run does not start with these."""
    rows, _ = coverage(b)
    out = [f"nothing measures: {r['need']}" for r in rows if r["status"] == "none"]
    out += [f"'{r['need']}' names a check that is not in `evaluate`: {c['label']}"
            for r in rows for c in r["checks"] if not c["known"]]
    return out


def plan(b, reg):
    """The bench's checks, one row each, for the user to choose from: which requirement it answers,
    whether the metric was written for this bench or comes from the library, and what fails it."""
    need_of = {}
    for r in b.get("requirements") or []:
        for n in (r.get("checks") or []) if isinstance(r, dict) else []:
            need_of.setdefault(n, []).append(r.get("need", ""))
    rows = []
    for dim, spec in (b.get("evaluate") or {}).items():
        for opt in spec.get("metrics", []):
            m = reg.get(opt["id"]) or {}
            if opt.get("id") in JUDGED:  # built in, not a metric file
                m = {"source": "library", "meta": {"trust": "judge", "description": {
                    "vlm_checklist": "Yes/no questions put to the vision judges; passes when most judges say yes to every question.",
                    "vlm_same_object": "The vision judges are asked whether the output shows the same object as the input; passes when most say yes.",
                    "vlm_rubric": "The vision judges score the output on a scale against a written rubric."}[opt["id"]]}}
            limit = ", ".join(f"{k} {opt[k]}" for k in LIMIT_KEYS if k in opt)
            if opt.get("limitFrom"):
                limit += " (set from the first full run)"
            elif not limit and opt.get("limit") != "none" and opt.get("id") not in YES_NO and (
                    opt.get("id") == "vlm_rubric" or (m.get("meta") or {}).get("direction")):
                limit = "worse than the typical recipe (set from the first full run)"
            if not limit and opt.get("id") in YES_NO:
                limit = "yes on every question"
            rows.append({"label": label(opt), "id": opt["id"], "dimension": dim,
                         "origin": {"bench": "written for this bench", "library": "library"}.get(m.get("source"), m.get("source") or "unknown"),
                         "trust": (m.get("meta") or {}).get("trust", ""), "limit": limit or "none (measured only)",
                         "needs": need_of.get(label(opt), []), "what": (m.get("meta") or {}).get("description", ""),
                         "questions": opt.get("questions") or []})
    return rows


NAMES = {
    "size_aspect": "Aspect", "phase_correlation": "Shift", "mask_iou": "Outline", "deltaE2000_region": "Colour",
    "ssim_region": "Structure", "sharpness_laplacian": "Sharpness", "ocr_cer": "Text", "ocr_extra_text": "Extra text",
    "vlm_checklist": "Judge checklist", "vlm_rubric": "Judge rubric", "vlm_same_object": "Same object",
}
REGION_NAMES = {"product": "", "not(product)": "backdrop"}


def label(opt):
    """Readable column name. `label:` in bench.yaml wins; otherwise metric name plus region."""
    if opt.get("label"):
        return opt["label"]
    name = NAMES.get(opt["id"], opt["id"].replace("_", " ").capitalize())
    region = opt.get("region")
    region = REGION_NAMES.get(region, region) if region else ""
    return f"{name} ({region})" if region else name


JUDGED = ("vlm_checklist", "vlm_same_object", "vlm_rubric")


def score_pair(b, p, pending=None, recipe=None, reg=None):
    """Deterministic metrics now; vision-model metrics are queued in `pending` (run later, in parallel)."""
    rows = []
    copied = copied_regions(recipe)
    reg = reg if reg is not None else catalog.load(b)
    for dim, spec in (b.get("evaluate") or {}).items():
        for opt in spec.get("metrics", []):
            row = {"dimension": dim, "mode": row_mode(opt), "id": opt["id"], "label": label(opt),
                   "thresholds": thresholds(opt)}
            if opt["id"] in JUDGED:
                if pending is None:
                    rows.append({**row, "status": "not_run", "note": "vision judges switched off"})
                else:
                    row = {**row, "status": "pending", "kind": opt.get("kind")}
                    rows.append(row)
                    pending.append((row, p, opt))
                continue
            m = reg.get(opt["id"])
            if m is None:
                rows.append({**row, "status": "not_run",
                             "note": f"no metric file '{opt["id"]}' in the library or the bench's metrics/"})
                continue
            fn = m["compute"]
            row.update(metric_fp=m["fp"], metric_source=m["source"], kind=opt.get("kind") or m["meta"].get("kind"))
            if p.no_picture and m["meta"].get("family") != "vector":
                rows.append({**row, "status": "not_run", "note": f"the SVG could not be rendered: {p.no_picture}"})
                continue
            for_text = "text_output" in m["meta"].get("needs", [])
            if for_text != (p.text is not None):
                rows.append({**row, "status": "not_run", "note": "a check for text outputs: this output is not text"
                             if for_text else "a check for pictures: this output is text"})
                continue
            if m["meta"].get("copy_sensitive") and opt.get("region") in copied:
                rows.append({**row, "status": "not_run",
                             "note": "copied from the original by this recipe: a pass would be by construction"})
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
        if textmod.is_text(src):
            continue  # no unchanged copy of a text input can stand in for an output
        prod = (inp.get("regions") or {}).get("product")
        mask = os.path.join(b["_dir"], prod) if isinstance(prod, str) and not prod.startswith(("auto:", "detect:")) else None
        p = Pair(b, inp, src, mask)
        for dim, spec in (b.get("evaluate") or {}).items():
            for opt in spec.get("metrics", []):
                if row_mode(opt) != "gate":
                    continue
                m = reg.get(opt["id"])
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


def adapt(b, inp, f, what, out_dir, op, plain_mask):
    """A Pair for an output that is a cut-out, a mask, a vector file or text (see adapters.py), and what
    the report needs to show it. A plain picture comes back as it is, with nothing extra."""
    if what == "image":
        return Pair(b, inp, f, plain_mask()), None
    os.makedirs(os.path.join(out_dir, "renders"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "masks"), exist_ok=True)
    stem_ = os.path.basename(f).rsplit(".", 1)[0]
    view, cut = f"renders/{stem_}__{what}.png", f"masks/{stem_}_cut.png"
    vpath, cpath, facts_path = os.path.join(out_dir, view), os.path.join(out_dir, cut), os.path.join(
        out_dir, "renders", f"{stem_}__{what}.json")
    cached = os.path.exists(facts_path) and os.path.exists(vpath)
    facts = json.load(open(facts_path, encoding="utf8")) if cached else None
    if what == "text":
        text = textmod.read(f)
        if not cached:
            size = input_rgb(b, inp)[1]
            textmod.card(text, size).save(vpath)
            facts = {"words": len(textmod.words(text)), "chars": len(text)}
        p = Pair(b, inp, vpath, None)
        p.text, p.text_meta = text, {k: op[k] for k in ("finishReason", "usage") if op.get(k) is not None}
        entry = {"view": view, "text": text, "native": f"{facts['words']} words"}
    elif what == "vector":
        if not cached:
            facts = adapters.svg(f, vpath, input_rgb(b, inp)[1][0])
            if facts.get("render_error"):  # the file is kept and its facts are read; there is no picture to check
                textmod.card(f"This SVG could not be rendered:\n{facts['render_error']}", input_rgb(b, inp)[1]).save(vpath)
        p = Pair(b, inp, vpath, None)
        p.svg, p.no_picture = facts, facts.get("render_error")
        entry = {"view": view, "view_info": facts,
                 "native": f"SVG · {facts['shapes']} shapes · {facts['file_kb']:.0f} KB"
                           + (f" · {facts['images']} embedded bitmap(s)" if facts["images"] else "")
                           + (" · not rendered" if facts.get("render_error") else "")}
    else:
        if not (cached and os.path.exists(cpath)):
            facts = (adapters.cutout(f, vpath, cpath) if what == "cutout"
                     else adapters.mask(f, input_rgb(b, inp)[0], vpath, cpath))
        p = Pair(b, inp, vpath, cpath)
        p.out_is_outline = True
        if what == "cutout":
            p.alpha_file = f
        entry = {"view": view, "view_mask": cut, "view_info": facts,
                 "native": f"{facts['width']}x{facts['height']}"
                           + ("" if what == "mask" or facts.get("has_alpha") else " · no transparency")}
    p.out_file = f
    if not cached:
        json.dump(facts, open(facts_path, "w", encoding="utf8"))
    return p, {"entry": entry}


def find_mask(out_dir, fname, recipe):
    for c in (os.path.join(out_dir, "masks", fname.rsplit(".", 1)[0] + "_cut.png"),
              os.path.join(out_dir, "masks", f"{recipe}_cut.png")):
        if os.path.exists(c):
            return c
    return None


def pixel_fails(metrics):
    return sum(1 for m in metrics if m["mode"] == "gate" and m["id"] not in JUDGED and m.get("pass") is False)


OUT_RE = re.compile(r"(.+?)__(.+?)__s(\d+)\.\w+$")


def spent_on(results):
    """What a run folder's results cost: generations made here (not the ones copied from another
    folder) plus everything spent on outlines for them."""
    return sum((0 if r.get("reused_from") else (r.get("spend", r.get("cost")) or 0)) + (r.get("eval_cost") or 0)
               for r in results)


def recheck(b, data, out_dir):
    """Limits were just set from this scoring (limits.py): judge the values it measured against them.
    Nothing is measured again, and no judge is asked again."""
    by_label = {label(opt): opt for _, opt in all_checks(b)}
    max_failed = (b.get("judgeWhen") or {}).get("maxFailedChecks", 1)
    for entry in data["scored"]:
        for row in entry["metrics"]:
            opt = by_label[row["label"]]
            row.update(mode=row_mode(opt), thresholds=thresholds(opt))
            if row["status"] == "ok":
                row["pass"] = check(row["values"], opt) if row["mode"] == "gate" else None
        # the judge funnel, as any later scoring applies it: an output that now fails too many pixel checks
        # is not judged, so the answers it got before there were limits are not counted
        fails = pixel_fails(entry["metrics"])
        if fails > max_failed:
            for row in entry["metrics"]:
                if row["id"] in JUDGED and row["status"] == "ok":
                    for k in ("values", "pass"):
                        row.pop(k, None)
                    row.update(status="not_run", note=f"skipped: failed {fails} pixel checks")
    data["controls"] = controls(b, catalog.load(b))  # the new limits are tested on unchanged inputs too
    json.dump(data, open(os.path.join(out_dir, "scores.json"), "w", encoding="utf8"), indent=1)
    return data


def score_all(b, out_dir, results=None, judges=True, maxSpend=None, log=print):
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
    if panel:
        try:
            judge_mod.api.api_key()
        except judge_mod.api.RunwareError:
            panel.offline = True
            log("No Runware login: vision judges use cached answers only; new questions are skipped.")
    max_failed = (b.get("judgeWhen") or {}).get("maxFailedChecks", 1)
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
        elif video_mod.is_video(f):
            # frame adapter: the first frame is the output image; video checks read the frame sequence,
            # and the sample frames (with the outlines the run bought for them) carry the product checks
            clip = video_mod.ensure(f, out_dir, log)
            vp = video_mod.paths(out_dir, f)
            p = Pair(b, inputs[inp], vp["first"], find_mask(out_dir, fname, recipe))
            p.video = {**clip, "frames": video_mod.frames(f, bars=clip["bars"]),
                       "sample_files": [{**smp, "file": vp["sample"](smp["k"]),
                                         "mask": vp["mask"](smp["k"]) if os.path.exists(vp["mask"](smp["k"])) else None}
                                        for smp in clip.get("samples") or []]}
        else:
            op = ops.get(fname, {})
            what = adapters.kind(f, op.get("task_type") or recipes_by_id.get(recipe, {}).get("taskType"))
            p, view = adapt(b, inputs[inp], f, what, out_dir, op, lambda: find_mask(out_dir, fname, recipe))
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
                 "sha1": hashlib.sha1(open(f, "rb").read()).hexdigest(),  # two draws with the same file are one draw
                 "native": f"{p.native[0]}x{p.native[1]}", "cost": r.get("cost"),
                 "latency_s": r.get("latency_s"), "metrics": metrics}
        if r.get("picked_model"):
            entry["picked_model"] = r["picked_model"]
        if view and "entry" in view:
            entry.update(view["entry"])  # a cut-out, mask, vector file or text: see adapt()
        elif view:
            stem_ = fname.rsplit(".", 1)[0]
            entry.update(view=f"renders/{stem_}__front.png", view_mask=f"renders/{stem_}__front_cut.png",
                         turntable=f"renders/{stem_}__turntable.jpg", view_info=view,
                         turn_title="All around (0°, 90°, 180°, 270°)",
                         native=f"{view['mesh']['faces']:,} faces")
        if p.video:
            stem_ = fname.rsplit(".", 1)[0]
            mask = find_mask(out_dir, fname, recipe)
            entry.update(view=f"renders/{stem_}__first.png",
                         view_mask=os.path.relpath(mask, out_dir).replace(os.sep, "/") if mask else None,
                         turntable=f"renders/{stem_}__frames.jpg", turn_title="First, middle and last frame",
                         clip=f"renders/{stem_}__preview.mp4" if clip.get("preview") else None,
                         view_info={k: v for k, v in clip.items()},
                         native=f"{clip['width']}x{clip['height']} · {clip['duration']:.1f}s"
                                + (f" · black bars, picture {clip['content_width']}x{clip['content_height']}"
                                   if clip["bars_share"] else ""))
        scored.append(entry)
    if pending:
        # budget check after the pixel funnel: only outputs that will actually be judged count
        calls = len(pending) * len(panel.judges)
        projected = calls * judge_mod.EST_COST_PER_CALL
        spent = spent_on(results or [])
        log(f"Vision judges: {len(pending)} output(s) passed the pixel funnel (at most {max_failed} failed "
            f"check(s)); up to {calls} calls, about ${projected:.2f} (cached answers are free).")
        if maxSpend is not None and spent + projected > maxSpend:
            log(f"Skipping vision judges: ${spent + projected:.2f} would exceed the ${maxSpend:.2f} cap.")
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
