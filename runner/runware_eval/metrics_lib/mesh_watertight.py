"""Is the 3D output a closed surface?"""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mesh_watertight',
    'trust': 'deterministic',
    'family': 'mesh',
    'kind': 'info',
    'needs': ['mesh'],
    'unit': '1 / 0',
    'direction': '',
    'description': 'Is the 3D output a closed surface?',
}


def compute(pair, opt):
    return mesh_value(pair, 'watertight')
