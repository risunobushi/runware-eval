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
    "sharpness_laplacian": m_sharpness_laplacian,
}
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


def score_pair(b, p):
    rows = []
    for dim, spec in (b.get("evaluate") or {}).items():
        for opt in spec.get("metrics", []):
            fn = TASK_SPECIFIC.get(opt.get("name")) if opt["id"] == "task_specific" else METRICS.get(opt["id"])
            row = {"dimension": dim, "mode": spec.get("mode", "gate"), "id": opt["id"], "label": label(opt),
                   "thresholds": {k: v for k, v in opt.items() if k not in ("id", "name", "label", "region", "rule", "on",
                                                                          "judges", "questions", "rubric")}}
            if fn is None:
                rows.append({**row, "status": "not_run", "note": "not implemented in this runner version"})
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


def score_all(b, out_dir, results=None):
    """Score every output file in out_dir. Uses results.jsonl for cost and latency when present."""
    ops = {r["file"]: r for r in (results or []) if r.get("status") == "success" and r.get("file")}
    inputs = {stem(i["path"]): i for i in b["inputs"]}
    scored = []
    for f in sorted(glob.glob(os.path.join(out_dir, "*__*__s*.*"))):
        fname = os.path.basename(f)
        inp, recipe, seed = re.match(r"(.+?)__(.+?)__s(\d+)\.\w+$", fname).groups()
        if inp not in inputs:
            continue
        p = Pair(b, inputs[inp], f, find_mask(out_dir, fname, recipe))
        r = ops.get(fname, {})
        scored.append({"input": inp, "recipe": recipe, "seed": int(seed), "file": fname,
                       "native": f"{p.native[0]}x{p.native[1]}", "cost": r.get("cost"),
                       "latency_s": r.get("latency_s"), "metrics": score_pair(b, p)})
    errors = [r for r in (results or []) if r.get("status") == "error"]
    attempted = [{"recipe": r["recipe"], "input": r["input"]} for r in (results or [])]
    data = {"scored": scored, "errors": errors, "attempted": attempted}
    json.dump(data, open(os.path.join(out_dir, "scores.json"), "w", encoding="utf8"), indent=1)
    return data
