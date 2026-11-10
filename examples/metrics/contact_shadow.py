"""Lightness drop in a band just below the product, against the nearby backdrop."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'contact_shadow',
    'trust': 'deterministic',
    'family': 'lighting',
    'kind': 'change',
    'needs': ['region'],
    'unit': 'L*',
    'direction': 'higher',
    'description': 'Lightness drop in a band just below the product, against the nearby backdrop.',
}


def compute(p, opt):
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
