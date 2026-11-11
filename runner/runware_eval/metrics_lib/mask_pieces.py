"""Separate pieces in the cut-out or mask, counting only pieces above 0.05% of the frame (or 5% of the selection, when that is smaller). One product is one piece: more means stray islands of backdrop, or a subject cut apart. Also reports the share of the selection in the largest piece and the holes inside it."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mask_pieces',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'info',
    'needs': [],
    'unit': 'pieces',
    'direction': 'lower',
    'description': 'Separate pieces in the cut-out or mask, counting only pieces above 0.05% of the frame (or 5% of the selection, when that is smaller). One product is one piece: more means stray islands of backdrop, or a subject cut apart. Also reports the share of the selection in the largest piece and the holes inside it.',
}


def _pieces(mask, floor):
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sorted((int(a) for a in stats[1:, cv2.CC_STAT_AREA] if a >= floor), reverse=True)


def compute(p, opt):
    m = own_outline(p)
    if not m.any():
        return {"value": 0.0, "largest_share": 0.0, "holes": 0}
    # small enough to catch a stray island next to a product, and to keep the pieces of a small mask (eyes, lips)
    floor = max(16, min(m.size * float(opt.get("min_share", 0.0005)), m.sum() * 0.05))
    areas = _pieces(m, floor)
    holes = _pieces(~m, floor)[1:] if (~m).any() else []  # the largest unselected piece is the backdrop
    return {"value": float(len(areas)), "largest_share": float(areas[0] / m.sum()) if areas else 0.0,
            "holes": len(holes)}
