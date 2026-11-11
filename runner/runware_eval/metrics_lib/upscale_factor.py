"""How much larger the output is than the input: output width / input width (2.0 = twice as wide). Also reports the delivered size."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'upscale_factor',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'info',
    'needs': ['reference'],
    'unit': '× input',
    'direction': 'higher',
    'description': 'How much larger the output is than the input: output width / input width (2.0 = twice as wide). Also reports the delivered size.',
}


def compute(p, opt):
    ow, oh = p.native
    return {"value": float((ow / p.W + oh / p.H) / 2), "native": f"{ow}x{oh}"}
