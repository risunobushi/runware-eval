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
`opt` is the metric's entry in bench.yaml (region, thresholds and any options it defines).

Metrics run locally and must not use the network.
"""
import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

__all__ = ["np", "cv2", "rgb2lab", "deltaE_ciede2000", "structural_similarity", "erode", "mesh_value"]


def erode(mask, pct=0.15):
    """Shrink a mask by `pct` percent of the longest side (keeps anti-aliased edges out of a measurement)."""
    k = max(1, int(round(max(mask.shape) * pct / 100)))
    return cv2.erode(mask.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0


def mesh_value(pair, key):
    """A mesh fact as a metric value; raises KeyError for non-3D outputs (reported as 'not run')."""
    if not getattr(pair, "mesh", None):
        raise KeyError("not a 3D output")
    v = pair.mesh[key]
    return {"value": (1.0 if v else 0.0) if isinstance(v, bool) else float(v)}
