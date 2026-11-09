"""Triangles in all geometries of a 3D output."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'mesh_faces',
    'trust': 'deterministic',
    'family': 'mesh',
    'kind': 'info',
    'needs': ['mesh'],
    'unit': 'faces',
    'direction': '',
    'description': 'Triangles in all geometries of a 3D output.',
}


def compute(pair, opt):
    return mesh_value(pair, 'faces')
