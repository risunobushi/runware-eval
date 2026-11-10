"""Relight: mean lightness change of the backdrop (outside the product)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'backdrop_lightness',
    'trust': 'deterministic',
    'family': 'lightness',
    'kind': 'preserve',
    'needs': ['reference', 'region'],
    'unit': 'L*',
    'direction': 'closer_to_zero',
    'description': 'Relight: mean lightness change of the backdrop (outside the product).',
}


def compute(p, opt):
    bg = erode(~p.region("product")) & erode(~p.region("product", "out"))
    return {"value": float(p.lab_out[..., 0][bg].mean() - p.lab_in[..., 0][bg].mean())}
