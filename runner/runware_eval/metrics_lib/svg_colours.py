"""Distinct fill and stroke colours in the SVG. A brand mark should have a handful; hundreds means gradients were traced into flat steps."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'svg_colours',
    'trust': 'deterministic',
    'family': 'vector',
    'kind': 'info',
    'needs': [],
    'unit': 'colours',
    'direction': '',
    'description': 'Distinct fill and stroke colours in the SVG. A brand mark should have a handful; hundreds means gradients were traced into flat steps.',
}


def compute(p, opt):
    return svg_value(p, "colours")
