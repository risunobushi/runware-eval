"""Relight: how much more light falls on the left half of the product than before."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'lr_lighting_shift',
    'trust': 'deterministic',
    'family': 'lighting',
    'kind': 'change',
    'needs': ['reference', 'region'],
    'unit': 'L*',
    'direction': 'higher',
    'description': 'Relight: how much more light falls on the left half of the product than before.',
}


def compute(p, opt):
    cx = np.nonzero(p.region("product"))[1].mean()
    left = np.arange(p.W)[None, :] < cx

    def lr(L, m):
        return L[m & left].mean() - L[m & ~left].mean()
    return {"value": float(lr(p.lab_out[..., 0], p.region("product", "out")) - lr(p.lab_in[..., 0], p.region("product")))}
