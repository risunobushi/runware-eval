"""Does the output's outline overlap the input's? Intersection over union of the region masks."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_iou',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'IoU',
    'direction': 'higher',
    'description': "Does the output's outline overlap the input's? Intersection over union of the region masks.",
}


def compute(p, opt):
    a, b = p.region(opt.get("region", "product")), p.region(opt.get("region", "product"), "out")
    return {"value": float((a & b).sum() / max(1, (a | b).sum()))}
