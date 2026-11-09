"""Largest base-colour texture of a 3D output (0 = untextured)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mesh_texture_px',
    'trust': 'deterministic',
    'family': 'mesh',
    'kind': 'info',
    'needs': ['mesh'],
    'unit': 'px',
    'direction': '',
    'description': 'Largest base-colour texture of a 3D output (0 = untextured).',
}


def compute(pair, opt):
    return mesh_value(pair, 'texture_px')
