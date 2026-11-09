"""File size of a 3D output."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mesh_file_mb',
    'trust': 'deterministic',
    'family': 'mesh',
    'kind': 'info',
    'needs': ['mesh'],
    'unit': 'MB',
    'direction': '',
    'description': 'File size of a 3D output.',
}


def compute(pair, opt):
    return mesh_value(pair, 'file_mb')
