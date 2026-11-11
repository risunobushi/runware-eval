"""How much of its own bounding box the cut-out or mask fills (per piece, weighted by area): 1.0 is a plain rectangle, a traced subject is well below. Tells a detector's box from a real outline without any reference."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_box_fill',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'info',
    'needs': [],
    'unit': 'share of its box',
    'direction': '',
    'description': "How much of its own bounding box the cut-out or mask fills (per piece, weighted by area): 1.0 is a plain rectangle, a traced subject is well below. Tells a detector's box from a real outline without any reference.",
}


def compute(p, opt):
    m = own_outline(p)
    if not m.any():
        raise ValueError("the mask selects nothing")
    n, _, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    area = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    box = (stats[1:, cv2.CC_STAT_WIDTH] * stats[1:, cv2.CC_STAT_HEIGHT]).astype(np.float64)
    return {"value": float((area / box * area).sum() / area.sum())}
