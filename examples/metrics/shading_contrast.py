"""Relight: lightness spread inside the product, relative to the input (harder light = higher)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'shading_contrast',
    'trust': 'deterministic',
    'family': 'lighting',
    'kind': 'change',
    'needs': ['reference', 'region'],
    'unit': '× input',
    'direction': 'higher',
    'description': 'Relight: lightness spread inside the product, relative to the input (harder light = higher).',
}


def compute(p, opt):
    return {"value": float(p.lab_out[..., 0][p.region("product", "out")].std()
                           / p.lab_in[..., 0][p.region("product")].std())}
