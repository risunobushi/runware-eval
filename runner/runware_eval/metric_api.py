"""The stable API for metric files. A metric file does `from runware_eval.metric_api import *`.

A metric file is a small Python module with:

    META = {
        "id": "my_metric",            # what bench.yaml refers to
        "family": "colorimetric",     # used to pick cross-checks from a different family
        "trust": "deterministic",     # deterministic | learned | judge | human
        "kind": "preserve",           # preserve: an unchanged output must pass
                                      # change:   an unchanged output must fail (the task asks for change)
                                      # info:     no pass/fail meaning on its own
        "needs": ["reference", "region"],
        "unit": "ΔE", "direction": "lower",   # lower | higher | closer_to_zero
        "description": "One line a user can read.",
    }

    def compute(pair, opt):
        return {"value": ..., ...}    # `value` is what thresholds compare; extra keys are shown too

`pair` gives:
    pair.rgb_in, pair.rgb_out   float arrays (H, W, 3) in 0..1, output resampled to the input's size
    pair.lab_in, pair.lab_out   the same in CIELAB
    pair.region(spec, side)     bool mask: a region name, a `box`, or `not(<name>)`; side "in" | "out"
                                ("out" uses the output's own product mask when there is one)
    pair.W, pair.H, pair.native size of the input; native size of the output
    pair.boxes                  named boxes of the input
    pair.mesh                   mesh facts for 3D outputs (faces, parts, watertight, texture_px, file_mb), else None
    pair.m_out                  the output's own product mask, or None when there is none. For a cut-out
                                (removeBackground) or a mask (imageMasking) it is the output itself
    pair.input                  the input's entry in bench.yaml: per-input facts such as `reference`, `terms`
    text(pair)                  for text outputs (caption, textInference): the text. Raises KeyError otherwise
    text_part(pair, opt)        the text a text check reads: the answer without reasoning blocks, or, with
                                `field: <name>` on the check, that field of a JSON answer
    text_meta(pair, key)        `finishReason` or a `usage` count of a textInference answer
    words(text)                 lower-case words of a text
    alpha(pair)                 for cut-outs: the delivered alpha channel, 0..1, at the input's size
    native_out(pair)            the delivered picture at its own size (uint8 RGB): what upscale checks read
    svg_value(pair, key)        a fact of a vector output (shapes, nodes, colours, images, file_kb)
    own_outline(pair)           for cut-outs and masks: the outline the output is (bool, input's size)
    original(pair, region)      for upscales with ground truth: the input's `original:` picture, the output
                                at that size and the region at that size
    media(pair, name)           a reference image named at the top level of bench.yaml (a target background, a
                                style or lighting reference), resized to the input's size
    video_flow(pair)            for video outputs: optical flow between consecutive analysis frames, and the grey frames
    video(pair)                 for video outputs: a dict with `frames` (N, h, w, 3 uint8 RGB, `analysis_fps`
                                frames per second, longest side 384 px) and the clip's facts (duration,
                                native_fps, width, height). Raises KeyError for other outputs ('not run').
                                For a video, pair.rgb_out / lab_out are its first frame.
    video_samples(pair)         for video outputs: five frames spread from the first to the last, each a dict
                                with `t` (seconds), `rgb` (float, at the input's size) and `mask` (the product's
                                outline in that frame, bool, or None when the run bought none)
    video_outlines(pair)        the same, but raises KeyError ('not run') unless every sample has its outline
    ocr(pair, side, region)     the text a local OCR model reads off the input ("in") or the output ("out"), inside
                                a region if one is named: a list of {"text", "conf", "box"} in reading order
    squash(text), text_distance(needle, haystack)
                                a text without spaces and case, and the fewest edits that turn some stretch of
                                `haystack` into `needle`: how the OCR checks compare what was read with what was expected
    series(values, fps)         per-frame values as [[seconds, value], ...]: return it as `series` and the
                                report draws the measurement over time
`opt` is the metric's entry in bench.yaml (region, thresholds and any options it defines).

Metrics run locally and must not use the network.
"""
import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from .text import answer, reasoning, unfence, words

__all__ = ["np", "cv2", "rgb2lab", "deltaE_ciede2000", "structural_similarity", "erode", "mesh_value", "video",
           "out_mask", "video_flow", "media", "text", "text_meta", "words", "alpha", "native_out", "svg_value",
           "outline", "own_outline", "original", "plain_resize", "text_part", "answer", "reasoning", "unfence",
           "video_samples", "video_outlines", "series", "ocr", "squash", "text_distance"]

_OCR = []  # the OCR engine, loaded on first use (models ship with the runner; nothing is downloaded)


def ocr(pair, side="out", region=None, min_conf=0.5):
    """The text a local OCR model (RapidOCR, PP-OCR models, on the CPU) reads off the input or the output,
    at the input's size, inside `region`'s bounding box when one is named. A list of lines in reading
    order, each {"text", "conf" (0..1), "box" (x0, y0, x1, y1)}. Read once per picture and region.
    It reads Latin letters, digits and Chinese; small, curved or very stylised lettering is missed, and
    it does not keep spaces reliably: compare with `squash` and `text_distance`, not word by word."""
    if getattr(pair, "text", None) is not None:
        raise KeyError("a text output has no picture to read")
    cache = pair.__dict__.setdefault("_ocr", {})
    key = (side, region)
    if key not in cache:
        if not _OCR:
            from rapidocr_onnxruntime import RapidOCR
            _OCR.append(RapidOCR())
        rgb = pair.rgb_in if side == "in" else pair.rgb_out
        x0 = y0 = 0
        if region:
            ys, xs = np.nonzero(pair.region(region))
            if not len(ys):
                raise ValueError("the region is empty")
            pad = max(8, int(0.02 * max(rgb.shape[:2])))
            y0, x0 = max(0, ys.min() - pad), max(0, xs.min() - pad)
            rgb = rgb[y0:ys.max() + pad, x0:xs.max() + pad]
        img = cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        found, _ = _OCR[0](img)
        lines = []
        for box, txt, conf in found or []:
            px, py = [p[0] for p in box], [p[1] for p in box]
            lines.append({"text": str(txt).strip(), "conf": float(conf),
                          "box": (int(min(px)) + x0, int(min(py)) + y0, int(max(px)) + x0, int(max(py)) + y0)})
        h = float(np.median([l["box"][3] - l["box"][1] for l in lines])) if lines else 1.0
        lines.sort(key=lambda l: (round((l["box"][1] + l["box"][3]) / 2 / max(h, 1.0)), l["box"][0]))
        cache[key] = lines
    return [l for l in cache[key] if l["conf"] >= min_conf and l["text"]]


def squash(text, case=False):
    """A text as the OCR checks compare it: no spaces or line breaks, lower case unless `case`."""
    t = "".join(str(text).split())
    return t if case else t.lower()


def text_distance(needle, haystack):
    """The fewest single-character edits that turn some stretch of `haystack` into `needle` (0 = it is
    in there as written; len(needle) = nothing like it). Text before and after the stretch is free, so
    extra text around the expected string does not count."""
    prev = [0] * (len(haystack) + 1)
    for i, a in enumerate(needle, 1):
        cur = [i] + [0] * len(haystack)
        for j, b in enumerate(haystack, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b))
        prev = cur
    return min(prev)


def text(pair):
    """The text of a text output; raises KeyError for anything else ('not run')."""
    if getattr(pair, "text", None) is None:
        raise KeyError("not a text output")
    return pair.text


def text_part(pair, opt=None):
    """What a text check reads. The answer as delivered, minus any reasoning block the model left in it
    (`text_reasoning_leak` reports those). With `field: title` on the check: that field of a JSON answer
    (dots go deeper: `product.title`); raises ValueError when the answer is not JSON or has no such field."""
    import json
    t = answer(text(pair))
    field = (opt or {}).get("field")
    if not field:
        return t
    try:
        data = json.loads(unfence(t)[0])
    except ValueError:
        raise ValueError(f"`field: {field}` needs a JSON answer; this one is not valid JSON")
    for key in str(field).split("."):
        if not (isinstance(data, dict) and key in data):
            raise ValueError(f"the JSON answer has no field `{field}`")
        data = data[key]
    return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)


def text_meta(pair, key):
    """`finishReason`, or a count from `usage` (promptTokens, completionTokens, totalTokens, thinkingTokens),
    as Runware reported it for a textInference answer. Raises KeyError when the answer did not carry it."""
    meta = getattr(pair, "text_meta", None) or {}
    v = meta.get(key, (meta.get("usage") or {}).get(key))
    if v is None:
        raise KeyError(f"the result does not say `{key}` (only textInference reports it)")
    return v


def alpha(pair):
    """The alpha channel a background removal delivered, 0..1, at the input's size."""
    if not getattr(pair, "alpha_file", None):
        raise KeyError("not a cut-out (removeBackground output)")
    from PIL import Image
    a = Image.open(pair.alpha_file).convert("RGBA").split()[-1]
    if a.size != (pair.W, pair.H):
        a = a.resize((pair.W, pair.H), Image.BILINEAR)
    return np.asarray(a).astype(np.float64) / 255.0


def native_out(pair):
    """The delivered picture at its own size, uint8 RGB. Raises KeyError for outputs that are not a picture."""
    if any(getattr(pair, k, None) is not None for k in ("text", "svg", "mesh", "video")):
        raise KeyError("not a picture output")
    from PIL import Image
    return np.asarray(Image.open(pair.out_file).convert("RGB"))


def svg_value(pair, key):
    """A fact of a vector output as a metric value; raises KeyError for anything else ('not run')."""
    if not getattr(pair, "svg", None):
        raise KeyError("not a vector output")
    if pair.svg.get("error"):
        raise ValueError(pair.svg["error"])
    return {"value": float(pair.svg[key])}


def outline(mask):
    """The edge pixels of a mask (its outline, one pixel wide)."""
    m = mask.astype(np.uint8)
    return (m > 0) & ~(cv2.erode(m, np.ones((3, 3), np.uint8)) > 0)


def media(pair, name, fit=True):
    """A top-level media entry of bench.yaml (e.g. `background: { path: ... }`, a style or lighting
    reference) as a float RGB array in 0..1. `fit` resizes it to the input's size, so it lines up with
    pair.rgb_out. Raises KeyError when the bench has no such entry ('not run')."""
    entry = getattr(pair, "bench", {}).get(name)
    if not (isinstance(entry, dict) and "path" in entry):
        raise KeyError(f"'{name}' is not a top-level media entry in bench.yaml")
    import os
    from PIL import Image
    im = Image.open(os.path.join(pair.bench["_dir"], entry["path"])).convert("RGB")
    if fit and im.size != (pair.W, pair.H):
        im = im.resize((pair.W, pair.H), Image.BICUBIC)
    return np.asarray(im).astype(np.float64) / 255.0


def erode(mask, pct=0.15):
    """Shrink a mask by `pct` percent of the longest side (keeps anti-aliased edges out of a measurement)."""
    k = max(1, int(round(max(mask.shape) * pct / 100)))
    return cv2.erode(mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0


def video(pair):
    """The frame sequence and facts of a video output; raises KeyError for anything else."""
    v = getattr(pair, "video", None)
    if not v:
        raise KeyError("not a video output")
    return v


def video_flow(pair):
    """Dense optical flow between consecutive analysis frames of a video output: a list of (h, w, 2)
    arrays in pixels per frame, plus the grey frames. Computed once per output and shared by the
    video checks that need it."""
    v = video(pair)
    if "_flow" not in v:
        g = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in v["frames"]]
        v["_flow"] = ([cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 21, 3, 5, 1.1, 0) for a, b in zip(g, g[1:])], g)
    return v["_flow"]


def video_samples(pair):
    """The sample frames of a video output (video.SAMPLES of them, spread evenly from the first frame to
    the last, black bars left out), resized to the input's size like the first frame is. Each is a dict:
    `t` seconds into the clip, `rgb` float (H, W, 3) in 0..1, `mask` the product's outline in that frame
    (bool) or None. Loaded once per output."""
    v = video(pair)
    if "_samples" not in v:
        from PIL import Image
        out = []
        for smp in v.get("sample_files") or []:
            im = Image.open(smp["file"]).convert("RGB")
            if im.size != (pair.W, pair.H):
                im = im.resize((pair.W, pair.H), Image.BICUBIC)
            mask = None
            if smp.get("mask"):
                m = Image.open(smp["mask"]).convert("L")
                if m.size != (pair.W, pair.H):
                    m = m.resize((pair.W, pair.H), Image.BILINEAR)
                mask = np.asarray(m) > 127
            out.append({"t": smp["t"], "rgb": np.asarray(im).astype(np.float64) / 255.0, "mask": mask})
        v["_samples"] = out
    if not v["_samples"]:
        raise KeyError("no sample frames for this clip (scored by an older runner: score it again)")
    return v["_samples"]


def video_outlines(pair):
    """The sample frames, each with the product's outline. Raises KeyError when the run bought no frame
    outlines (`video: { masks: false }`, or a run folder from before they existed: run it again)."""
    smp = video_samples(pair)
    if any(x["mask"] is None for x in smp):
        raise KeyError("no product outline for the frames of this clip")
    return smp


def series(values, fps=None, times=None, start=0):
    """Per-frame values as [[seconds, value], ...] for the report's over-time charts. `fps` and `start`
    (the frame number of the first value) give the times, or pass `times` in seconds."""
    vals = [float(x) for x in values]
    ts = list(times) if times is not None else [(start + i) / float(fps) for i in range(len(vals))]
    return [[round(float(t), 3), round(v, 4)] for t, v in zip(ts, vals)]


def out_mask(pair, spec="product"):
    """The region as found in the output itself. Raises KeyError when the output has no mask of its own,
    so a check that compares outlines is reported as not run instead of comparing the input with itself."""
    if spec == "product" and pair.m_out is None:
        raise KeyError("no product mask for this output")
    return pair.region(spec, "out")


def mesh_value(pair, key):
    """A mesh fact as a metric value; raises KeyError for non-3D outputs (reported as 'not run')."""
    if not getattr(pair, "mesh", None):
        raise KeyError("not a 3D output")
    v = pair.mesh[key]
    return {"value": (1.0 if v else 0.0) if isinstance(v, bool) else float(v)}


def own_outline(pair):
    """The outline a cut-out or a mask is (bool, at the input's size). Raises KeyError for any other output."""
    if not getattr(pair, "out_is_outline", False) or pair.m_out is None:
        raise KeyError("not a cut-out or a mask")
    return pair.m_out


def original(pair, spec=None):
    """For an upscale bench with ground truth: the input's `original:` file (the full-size picture the
    input was shrunk from), the delivered picture brought to that size, and the region at that size
    (the whole frame without `spec`). All uint8 RGB / bool. Raises KeyError without an `original:`."""
    import os
    from PIL import Image
    path = (getattr(pair, "input", None) or {}).get("original")
    if not path:
        raise KeyError("this input has no `original:` picture")
    truth = np.asarray(Image.open(os.path.join(pair.bench["_dir"], path)).convert("RGB"))
    out = native_out(pair)
    h, w = truth.shape[:2]
    if out.shape[:2] != (h, w):
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_AREA if out.shape[0] > h else cv2.INTER_CUBIC)
    m = np.ones((h, w), bool) if not spec else cv2.resize(pair.region(spec).astype(np.uint8), (w, h),
                                                          interpolation=cv2.INTER_NEAREST) > 0
    if not m.any():
        raise ValueError("the region is empty")
    return truth, out, m


def plain_resize(pair, size):
    """The input enlarged by plain bicubic resampling to `size` (w, h), uint8 RGB: what any upscaler must beat."""
    return cv2.resize((pair.rgb_in * 255).round().astype(np.uint8), size, interpolation=cv2.INTER_CUBIC)
