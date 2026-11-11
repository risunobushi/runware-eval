"""Delivered width and height over the input's (1.0 = the same size). For tools that should hand back the picture at its own size (background removal, masking, edits): below 1 the result came back smaller and resolution was lost. Also reports the delivered size."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'size_kept',
    'trust': 'deterministic',
    'family': 'geometric',
    'kind': 'preserve',
    'needs': ['reference'],
    'unit': '× input',
    'direction': 'higher',
    'tolerance': 0.05,  # smallest difference that counts (margin of a limit set from results)
    'description': "Delivered width and height over the input's (1.0 = the same size). For tools that should hand back the picture at its own size (background removal, masking, edits): below 1 the result came back smaller and resolution was lost. Also reports the delivered size.",
}


def compute(p, opt):
    if any(getattr(p, k, None) is not None for k in ("text", "svg", "mesh", "video")):
        raise KeyError("not a picture output")
    ow, oh = p.native
    return {"value": float(min(ow / p.W, oh / p.H)), "native": f"{ow}x{oh}"}
