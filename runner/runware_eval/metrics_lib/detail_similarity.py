"""Fine detail (lettering, stitching) kept? Best correlation of high-pass luminance over small offsets; survives lighting changes."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'detail_similarity',
    'trust': 'deterministic',
    'family': 'detail',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'NCC',
    'direction': 'higher',
    'copy_sensitive': True,
    'description': 'Fine detail (lettering, stitching) kept? Best correlation of high-pass luminance over small offsets; survives lighting changes.',
}


def compute(p, opt):
    """Illumination-invariant similarity of fine detail (lettering, stitching) inside a region: the
    best normalised cross-correlation of the high-pass luminance layers over small offsets (up to
    `search_px`, default 24), so outputs that are not pixel-aligned (re-framed images, 3D renders)
    are compared fairly. 1 = same detail, ~0 = unrelated."""
    sigma, pad = opt.get("sigma_px", 3), int(opt.get("search_px", 24))
    m = p.region(opt["region"])
    ys, xs = np.nonzero(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    hp = lambda L: (L - cv2.GaussianBlur(L, (0, 0), sigma)).astype(np.float32)
    a = hp(p.lab_in[..., 0])[y0:y1, x0:x1]
    Y0, Y1, X0, X1 = max(0, y0 - pad), min(p.H, y1 + pad), max(0, x0 - pad), min(p.W, x1 + pad)
    b = hp(p.lab_out[..., 0])[Y0:Y1, X0:X1]
    if b.shape[0] < a.shape[0] or b.shape[1] < a.shape[1] or a.std() < 1e-6:
        return {"value": float("nan")}
    res = cv2.matchTemplate(b, a, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(res)
    return {"value": float(best), "offset_px": [int(loc[0] - (x0 - X0)), int(loc[1] - (y0 - Y0))]}
