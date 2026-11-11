"""Size of the SVG file."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'svg_file_kb',
    'trust': 'deterministic',
    'family': 'vector',
    'kind': 'info',
    'needs': [],
    'unit': 'KB',
    'direction': 'lower',
    'description': 'Size of the SVG file.',
}


def compute(p, opt):
    return svg_value(p, "file_kb")
