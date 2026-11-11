"""Fine detail at the output's own size, relative to the input enlarged by plain resampling (1.0 = no more detail than a resize). More is not always better: detail the input never had is invented, so read it next to a fidelity check."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'upscale_detail_gain',
    'trust': 'deterministic',
    'family': 'signal',
    'kind': 'info',
    'needs': ['reference'],
    'unit': '× plain resize',
    'direction': 'higher',
    'description': "Fine detail at the output's own size, relative to the input enlarged by plain resampling (1.0 = no more detail than a resize). More is not always better: detail the input never had is invented, so read it next to a fidelity check.",
}


WINDOW = 3072  # the most pixels per side that are read, at the output's own size (keeps large upscales fast)


def compute(p, opt):
    out = native_out(p)
    oh, ow = out.shape[:2]
    if ow <= p.W and oh <= p.H:
        raise ValueError("the output is not larger than the input")
    sel = p.region(opt.get("region")).astype(np.uint8)
    ys, xs = np.nonzero(sel)
    cy, cx = int(ys.mean() * oh / p.H), int(xs.mean() * ow / p.W)  # a window around the region, at output size
    y0, x0 = max(0, min(oh - WINDOW, cy - WINDOW // 2)), max(0, min(ow - WINDOW, cx - WINDOW // 2))
    y1, x1 = min(oh, y0 + WINDOW), min(ow, x0 + WINDOW)
    src = cv2.resize((p.rgb_in * 255).astype(np.uint8), (ow, oh), interpolation=cv2.INTER_CUBIC)[y0:y1, x0:x1]
    m = cv2.resize(sel, (ow, oh), interpolation=cv2.INTER_NEAREST)[y0:y1, x0:x1] > 0
    if not m.any():
        raise ValueError("the region is empty at the output's size")
    lap = lambda rgb: cv2.Laplacian(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), cv2.CV_32F)[m].var()
    base = lap(src)
    if base <= 0:
        raise ValueError("the input has no detail in this region")
    return {"value": float(lap(np.ascontiguousarray(out[y0:y1, x0:x1])) / base)}
