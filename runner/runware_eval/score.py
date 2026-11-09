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

from . import judge as judge_mod
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


def erode(mask, pct=0.15):
    k = max(1, int(round(max(mask.shape) * pct / 100)))
    return cv2.erode(mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0


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

def m_size_aspect(p, opt):
    ow, oh = p.native
    return {"value": abs((ow / oh) / (p.W / p.H) - 1), "native": f"{ow}x{oh}"}


def m_phase_correlation(p, opt):
    a, b = p.region("product").astype(np.float32), p.region("product", "out").astype(np.float32)
    (dx, dy), _ = cv2.phaseCorrelate(a, b)
    return {"value": float(np.hypot(dx, dy))}


def m_mask_iou(p, opt):
    a, b = p.region(opt.get("region", "product")), p.region(opt.get("region", "product"), "out")
    return {"value": float((a & b).sum() / max(1, (a | b).sum()))}


def m_deltaE2000_region(p, opt):
    spec = opt.get("region")
    sel = erode(p.region(spec) & p.region(spec, "out"), opt.get("erode_pct", 0.15))
    lo, hi = opt.get("l_range", (0, 100))
    if "l_range" in opt:
        sel &= (p.lab_in[..., 0] > lo) & (p.lab_in[..., 0] < hi) & (p.lab_out[..., 0] > lo) & (p.lab_out[..., 0] < hi)
    a, b = p.lab_in[sel], p.lab_out[sel].copy()
    if opt.get("ignore_lightness"):
        b[:, 0] = a[:, 0]
    de = deltaE_ciede2000(a, b)
    return {"value": float(de.mean()), "mean": float(de.mean()), "p95": float(np.percentile(de, 95))}


def m_ssim_region(p, opt):
    spec = opt.get("region")
    m = p.region(spec)
    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    a, b = p.lab_in[y0:y1, x0:x1, 0].copy(), p.lab_out[y0:y1, x0:x1, 0].copy()
    mm = m[y0:y1, x0:x1]
    if opt.get("on") == "luminance_normalised":
        for arr in (a, b):
            arr -= arr[mm].mean()
            arr /= arr[mm].std() + 1e-6
    rng = max(a.max(), b.max()) - min(a.min(), b.min())
    _, smap = structural_similarity(a, b, data_range=rng, full=True)
    return {"value": float(smap[mm].mean())}


def _lum_crop(p, region, side_rgb):
    m = p.region(region)
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return rgb2lab(side_rgb[y0:y1, x0:x1])[..., 0], m[y0:y1, x0:x1]


def m_detail_similarity(p, opt):
    """Illumination-invariant similarity of fine detail (lettering, stitching) inside a region:
    normalised cross-correlation of the high-pass luminance layers. 1 = same detail, ~0 = unrelated."""
    sigma = opt.get("sigma_px", 3)
    a, m = _lum_crop(p, opt["region"], p.rgb_in)
    b, _ = _lum_crop(p, opt["region"], p.rgb_out)
    ha, hb = a - cv2.GaussianBlur(a, (0, 0), sigma), b - cv2.GaussianBlur(b, (0, 0), sigma)
    ha, hb = ha[m] - ha[m].mean(), hb[m] - hb[m].mean()
    return {"value": float((ha * hb).sum() / (np.sqrt((ha ** 2).sum() * (hb ** 2).sum()) + 1e-9))}


def m_keypoint_match(p, opt):
    """Share of the original's SIFT keypoints (inside the product) that find a geometrically consistent
    match in the output, at a coarse scale. Caution: tested on relighting, it tracks how much the light
    changed more than whether the product changed, so it is not a reliable identity gate there."""
    spec = opt.get("region", "product")
    sc = opt.get("side_px", 512) / max(p.W, p.H)   # coarse scale: generated images redraw micro-texture
    g = lambda rgb: cv2.resize(cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY), None,
                               fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
    m = lambda r: cv2.resize((r * 255).astype(np.uint8), None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=opt.get("max_points", 2000))
    ka, da = sift.detectAndCompute(g(p.rgb_in), m(p.region(spec)))
    kb, db = sift.detectAndCompute(g(p.rgb_out), m(p.region(spec, "out")))
    if da is None or db is None or len(ka) < 8 or len(kb) < 8:
        return {"value": 0.0, "points": len(ka or [])}
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [m for m, n in (x for x in pairs if len(x) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return {"value": len(good) / len(ka), "points": len(ka), "inliers": len(good)}
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    _, inl = cv2.findHomography(src, dst, cv2.RANSAC, opt.get("tolerance_px", 4.0))
    n = int(inl.sum()) if inl is not None else 0
    return {"value": n / len(ka), "points": len(ka), "inliers": n}


def m_seam_jump(p, opt):
    """Visible-compositing check for a locally edited region: brightness step across its border
    (blurred L* just inside vs just outside, per sector), minus the same step in the original."""
    m = p.region(opt["region"])
    band, gap = opt.get("band_px", 8), opt.get("gap_px", 3)
    ker = lambda r: np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    mu = m.astype(np.uint8)
    inner = (cv2.erode(mu, ker(gap)) > 0) & ~(cv2.erode(mu, ker(gap + band)) > 0)
    outer = (cv2.dilate(mu, ker(gap + band)) > 0) & ~(cv2.dilate(mu, ker(gap)) > 0)
    ys, xs = np.nonzero(m)
    cy, cx = ys.mean(), xs.mean()
    yy, xx = np.mgrid[0:p.H, 0:p.W]
    sector = ((np.arctan2(yy - cy, xx - cx) + np.pi) / (2 * np.pi) * 16).astype(int) % 16

    def jump(lab):
        L = cv2.GaussianBlur(lab[..., 0], (0, 0), 2)
        d = [abs(L[inner & (sector == k)].mean() - L[outer & (sector == k)].mean())
             for k in range(16) if (inner & (sector == k)).any() and (outer & (sector == k)).any()]
        return float(np.mean(d)) if d else float("nan")
    out_j, in_j = jump(p.lab_out), jump(p.lab_in)
    return {"value": out_j - in_j, "output_step": out_j, "original_step": in_j}


def m_sharpness_laplacian(p, opt):
    def sharp(rgb, m):
        g = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
        return cv2.Laplacian(g, cv2.CV_64F)[erode(m)].var()
    spec = opt.get("region")
    return {"value": float(sharp(p.rgb_out, p.region(spec, "out")) / sharp(p.rgb_in, p.region(spec)))}


def ts_lr_lighting_shift(p, opt):
    cx = np.nonzero(p.region("product"))[1].mean()
    left = np.arange(p.W)[None, :] < cx

    def lr(L, m):
        return L[m & left].mean() - L[m & ~left].mean()
    return {"value": float(lr(p.lab_out[..., 0], p.region("product", "out")) - lr(p.lab_in[..., 0], p.region("product")))}


def ts_shading_contrast(p, opt):
    return {"value": float(p.lab_out[..., 0][p.region("product", "out")].std()
                           / p.lab_in[..., 0][p.region("product")].std())}


def ts_backdrop_lightness(p, opt):
    bg = erode(~p.region("product")) & erode(~p.region("product", "out"))
    return {"value": float(p.lab_out[..., 0][bg].mean() - p.lab_in[..., 0][bg].mean())}


def ts_contact_shadow(p, opt):
    """Lightness drop in a band just below the product, against the nearby backdrop."""
    m = p.region("product")
    ys, xs = np.nonzero(m)
    y1, x0, x1 = ys.max(), xs.min(), xs.max()
    band = max(4, int(0.04 * p.H))
    below = np.zeros_like(m)
    below[y1:min(p.H, y1 + band), x0:x1] = True
    below &= ~m
    ref = np.zeros_like(m)
    ref[min(p.H - 1, y1 + 3 * band):min(p.H, y1 + 4 * band), x0:x1] = True
    L = p.lab_out[..., 0]
    return {"value": float(L[ref].mean() - L[below].mean()) if ref.any() and below.any() else float("nan")}


METRICS = {
    "size_aspect": m_size_aspect, "phase_correlation": m_phase_correlation, "mask_iou": m_mask_iou,
    "deltaE2000_region": m_deltaE2000_region, "ssim_region": m_ssim_region,
    "sharpness_laplacian": m_sharpness_laplacian, "detail_similarity": m_detail_similarity,
    "keypoint_match": m_keypoint_match, "seam_jump": m_seam_jump,
}
COPY_SENSITIVE = ("detail_similarity", "ssim_region", "deltaE2000_region")


def copied_regions(recipe):
    """Regions a recipe copies from the original in a post step: pixel similarity there is by construction."""
    return {list(s.values())[0] for s in (recipe or {}).get("post") or []
            if any(k in s for k in ("restore", "transfer_detail"))}
TASK_SPECIFIC = {
    "lr_lighting_shift": ts_lr_lighting_shift, "shading_contrast": ts_shading_contrast,
    "backdrop_lightness": ts_backdrop_lightness, "contact_shadow": ts_contact_shadow,
}


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


def score_pair(b, p, pending=None, recipe=None):
    """Deterministic metrics now; vision-model metrics are queued in `pending` (run later, in parallel)."""
    rows = []
    copied = copied_regions(recipe)
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
            fn = TASK_SPECIFIC.get(opt.get("name")) if opt["id"] == "task_specific" else METRICS.get(opt["id"])
            if fn is None:
                rows.append({**row, "status": "not_run", "note": "not implemented in this runner version"})
                continue
            if opt["id"] in COPY_SENSITIVE and opt.get("region") in copied:
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
    panel = judge_mod.Panel(b.get("judges"), out_dir, log) if judges else None
    max_failed = (b.get("judge_when") or {}).get("max_failed_checks", 1)
    recipes_by_id = {r["id"]: r for r in b.get("recipes") or [] if isinstance(r, dict)}
    scored, pending = [], []
    for f in files:
        fname = os.path.basename(f)
        inp, recipe, seed = OUT_RE.match(fname).groups()
        p = Pair(b, inputs[inp], f, find_mask(out_dir, fname, recipe))
        jobs = [] if panel else None
        metrics = score_pair(b, p, jobs, recipes_by_id.get(recipe))
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
        scored.append({"input": inp, "recipe": recipe, "seed": int(seed), "file": fname,
                       "native": f"{p.native[0]}x{p.native[1]}", "cost": r.get("cost"),
                       "latency_s": r.get("latency_s"), "metrics": metrics})
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
    data = {"scored": scored, "errors": errors, "attempted": attempted,
            "attempted_rows": [{"eval_cost": r.get("eval_cost")} for r in (results or [])],
            "judges": panel.judges if panel else [], "judge_cost": judge_mod.total_cost(out_dir)}
    json.dump(data, open(os.path.join(out_dir, "scores.json"), "w", encoding="utf8"), indent=1)
    return data
