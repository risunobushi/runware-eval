"""How much of what the mask selects lies inside the reference region (1 = all of it). For a mask of a part (a face, a hand) checked against the outline of the whole (the person): the part must sit inside it."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_inside',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'share of the mask',
    'direction': 'higher',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': 'How much of what the mask selects lies inside the reference region (1 = all of it). For a mask of a part (a face, a hand) checked against the outline of the whole (the person): the part must sit inside it.',
}


def compute(p, opt):
    a, b = p.region(opt.get("region", "product")), own_outline(p)
    if not b.any():
        raise ValueError("the mask selects nothing")
    return {"value": float((a & b).sum() / b.sum())}
