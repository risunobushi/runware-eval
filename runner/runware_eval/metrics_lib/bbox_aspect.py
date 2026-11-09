"""Proportions: relative difference of the region's bounding-box width/height ratios."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'bbox_aspect',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'ratio error',
    'direction': 'lower',
    'description': "Proportions: relative difference of the region's bounding-box width/height ratios.",
}


def compute(p, opt):
    """Proportions: relative difference between the width/height ratios of the product's bounding box."""
    def ratio(m):
        ys, xs = np.nonzero(m)
        return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
    spec = opt.get("region", "product")
    return {"value": float(abs(ratio(p.region(spec, "out")) / ratio(p.region(spec)) - 1))}
