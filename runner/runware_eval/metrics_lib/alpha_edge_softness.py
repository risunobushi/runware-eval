"""Width of the cut-out's semi-transparent edge, in pixels at the input's size: about 0 is a hard, jagged edge, 1 to 3 a clean anti-aliased one, more a soft matte (hair, fur, glass) or a halo. No better direction on its own."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'alpha_edge_softness',
    'trust': 'deterministic',
    'family': 'signal',
    'kind': 'info',
    'needs': [],
    'unit': 'px',
    'direction': '',
    'description': "Width of the cut-out's semi-transparent edge, in pixels at the input's size: about 0 is a hard, jagged edge, 1 to 3 a clean anti-aliased one, more a soft matte (hair, fur, glass) or a halo. No better direction on its own.",
}


def compute(p, opt):
    a = alpha(p)
    line = outline(a > 0.5)
    edge = line.sum()
    if not edge:
        raise ValueError("the cut-out has no edge: nothing or everything was kept")
    # only near the outline (2% of the longest side): a subject left faintly see-through all over is
    # not a soft edge (alpha_opacity reports that)
    k = max(3, int(round(max(a.shape) * 0.02)))
    near = cv2.dilate(line.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0
    return {"value": float(((a > 0.02) & (a < 0.98) & near).sum() / edge)}
