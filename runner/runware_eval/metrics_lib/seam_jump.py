"""Visible compositing: brightness step across a region's border, minus the step already in the input."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'seam_jump',
    'trust': 'deterministic',
    'family': 'compositing',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'L* step',
    'direction': 'lower',
    'tolerance': 1.0,  # smallest difference that counts (margin of a limit set from results)
    'description': "Visible compositing: brightness step across a region's border, minus the step already in the input.",
}


def compute(p, opt):
    """Visible-compositing check for a locally edited region: brightness step across its border
    (blurred L* just inside vs just outside, per sector), minus the same step in the original."""
    m = p.region(opt["region"])
    band, gap = opt.get("band_px", 8), opt.get("gap_px", 3)
    ker = lambda r: np.ones((2 * r + 1, 2 * r + 1), np.uint8)
    mu = m.astype(np.uint8)
    inner = (cv2.erode(mu, ker(gap)) > 0) & ~(cv2.erode(mu, ker(gap + band)) > 0)
    outer = (cv2.dilate(mu, ker(gap + band)) > 0) & ~(cv2.dilate(mu, ker(gap)) > 0)
    ys, xs = np.nonzero(m)
    cy, cx = ys.mean(), xs.mean()
    yy, xx = np.mgrid[0:p.H, 0:p.W]
    sector = ((np.arctan2(yy - cy, xx - cx) + np.pi) / (2 * np.pi) * 16).astype(int) % 16

    def jump(lab):
        L = cv2.GaussianBlur(lab[..., 0], (0, 0), 2)
        d = [abs(L[inner & (sector == k)].mean() - L[outer & (sector == k)].mean())
             for k in range(16) if (inner & (sector == k)).any() and (outer & (sector == k)).any()]
        return float(np.mean(d)) if d else float("nan")
    out_j, in_j = jump(p.lab_out), jump(p.lab_in)
    return {"value": out_j - in_j, "output_step": out_j, "original_step": in_j}
