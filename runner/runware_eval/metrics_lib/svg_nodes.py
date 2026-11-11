"""Anchor points over all shapes of the SVG: how heavy the drawing is to edit and render."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'svg_nodes',
    'trust': 'deterministic',
    'family': 'vector',
    'kind': 'info',
    'needs': [],
    'unit': 'nodes',
    'direction': 'lower',
    'description': 'Anchor points over all shapes of the SVG: how heavy the drawing is to edit and render.',
}


def compute(p, opt):
    return svg_value(p, "nodes")
