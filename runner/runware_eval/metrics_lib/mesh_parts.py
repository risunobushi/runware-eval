"""Connected components of a 3D output (thousands = fragmented)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mesh_parts',
    'trust': 'deterministic',
    'family': 'mesh',
    'kind': 'info',
    'needs': ['mesh'],
    'unit': 'count',
    'direction': '',
    'description': 'Connected components of a 3D output (thousands = fragmented).',
}


def compute(pair, opt):
    return mesh_value(pair, 'parts')
