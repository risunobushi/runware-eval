"""Drawing elements in the SVG (paths, rectangles, circles ...). Fewer is easier to edit; thousands means a traced photo."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'svg_shapes',
    'trust': 'deterministic',
    'family': 'vector',
    'kind': 'info',
    'needs': [],
    'unit': 'shapes',
    'direction': 'lower',
    'description': 'Drawing elements in the SVG (paths, rectangles, circles ...). Fewer is easier to edit; thousands means a traced photo.',
}


def compute(p, opt):
    return svg_value(p, "shapes")
