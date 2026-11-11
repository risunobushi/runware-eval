"""Bitmaps embedded in the SVG. Anything above 0 is a picture in an SVG wrapper, not a vector drawing: gate with `max: 0`."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'svg_images',
    'trust': 'deterministic',
    'family': 'vector',
    'kind': 'info',
    'needs': [],
    'unit': 'bitmaps',
    'direction': 'lower',
    'description': 'Bitmaps embedded in the SVG. Anything above 0 is a picture in an SVG wrapper, not a vector drawing: gate with `max: 0`.',
}


def compute(p, opt):
    return svg_value(p, "images")
