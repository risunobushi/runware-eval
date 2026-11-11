"""How far did the product move? Phase correlation between input and output product masks."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'phase_correlation',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'px',
    'direction': 'lower',
    'tolerance': 2,  # smallest difference that counts (margin of a limit set from results)
    'description': 'How far did the product move? Phase correlation between input and output product masks.',
}


def compute(p, opt):
    a, b = p.region("product").astype(np.float32), out_mask(p).astype(np.float32)
    (dx, dy), _ = cv2.phaseCorrelate(a, b)
    return {"value": float(np.hypot(dx, dy))}
