"""How far the output's outline is from the reference outline: mean distance in pixels at the input's size, both ways (also p95). Catches a ragged or shifted edge that overlap (mask_iou) hides on a large shape."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_boundary_px',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'px',
    'direction': 'lower',
    'tolerance': 2,  # smallest difference that counts (margin of a limit set from results)
    'description': "How far the output's outline is from the reference outline: mean distance in pixels at the input's size, both ways (also p95). Catches a ragged or shifted edge that overlap (mask_iou) hides on a large shape.",
}


def compute(p, opt):
    spec = opt.get("region", "product")
    a, b = outline(p.region(spec)), outline(out_mask(p, spec))
    if not a.any():
        raise ValueError("the reference region is empty")
    if not b.any():  # nothing selected, or the whole frame: as far off as an outline can be
        d = float(np.hypot(p.W, p.H))
        return {"value": d, "mean": d, "p95": d}
    dist = lambda edge: cv2.distanceTransform((~edge).astype(np.uint8), cv2.DIST_L2, 3)
    d = np.concatenate([dist(a)[b], dist(b)[a]])
    return {"value": float(d.mean()), "mean": float(d.mean()), "p95": float(np.percentile(d, 95))}
