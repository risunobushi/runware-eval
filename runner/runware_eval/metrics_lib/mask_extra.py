"""How much the output selects or keeps outside the reference region, as a share of the reference's area (0 = nothing extra). For a cut-out: background left in."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_extra',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'share of the reference',
    'direction': 'lower',
    'description': "How much the output selects or keeps outside the reference region, as a share of the reference's area (0 = nothing extra). For a cut-out: background left in.",
}


def compute(p, opt):
    spec = opt.get("region", "product")
    a, b = p.region(spec), out_mask(p, spec)
    return {"value": float((b & ~a).sum() / max(1, a.sum()))}
