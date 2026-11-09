"""Structural similarity of luminance inside a region (option on: luminance_normalised)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'ssim_region',
    'trust': 'deterministic',
    'family': 'structural',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'SSIM',
    'direction': 'higher',
    'copy_sensitive': True,
    'description': 'Structural similarity of luminance inside a region (option on: luminance_normalised).',
}


def compute(p, opt):
    spec = opt.get("region")
    m = p.region(spec)
    ys, xs = np.nonzero(m)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    a, b = p.lab_in[y0:y1, x0:x1, 0].copy(), p.lab_out[y0:y1, x0:x1, 0].copy()
    mm = m[y0:y1, x0:x1]
    if opt.get("on") == "luminance_normalised":
        for arr in (a, b):
            arr -= arr[mm].mean()
            arr /= arr[mm].std() + 1e-6
    rng = max(a.max(), b.max()) - min(a.min(), b.min())
    _, smap = structural_similarity(a, b, data_range=rng, full=True)
    return {"value": float(smap[mm].mean())}
