"""Did the output keep the input's proportions? Relative error of width/height; also reports the native size."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'size_aspect',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference'],
    'unit': 'aspect ratio error',
    'direction': 'lower',
    'description': "Did the output keep the input's proportions? Relative error of width/height; also reports the native size.",
}


def compute(p, opt):
    ow, oh = p.native
    return {"value": abs((ow / oh) / (p.W / p.H) - 1), "native": f"{ow}x{oh}"}
