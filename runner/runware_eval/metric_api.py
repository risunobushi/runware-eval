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
    pair.m_out                  the output's own product mask, or None when there is none
    media(pair, name)           a reference image named at the top level of bench.yaml (a target background, a
                                style or lighting reference), resized to the input's size
    video_flow(pair)            for video outputs: optical flow between consecutive analysis frames, and the grey frames
    video(pair)                 for video outputs: a dict with `frames` (N, h, w, 3 uint8 RGB, `analysis_fps`
                                frames per second, longest side 384 px) and the clip's facts (duration,
                                native_fps, width, height). Raises KeyError for other outputs ('not run').
                                For a video, pair.rgb_out / lab_out are its first frame.
`opt` is the metric's entry in bench.yaml (region, thresholds and any options it defines).

Metrics run locally and must not use the network.
"""
import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

__all__ = ["np", "cv2", "rgb2lab", "deltaE_ciede2000", "structural_similarity", "erode", "mesh_value", "video",
           "out_mask", "video_flow", "media"]


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
