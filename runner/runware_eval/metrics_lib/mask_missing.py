"""How much of the reference region the output leaves out (0 = nothing missing). For a cut-out: parts of the subject cut away."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_missing',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'share of the reference',
    'direction': 'lower',
    'description': 'How much of the reference region the output leaves out (0 = nothing missing). For a cut-out: parts of the subject cut away.',
}


def compute(p, opt):
    spec = opt.get("region", "product")
    a, b = p.region(spec), out_mask(p, spec)
    return {"value": float((a & ~b).sum() / max(1, a.sum()))}
