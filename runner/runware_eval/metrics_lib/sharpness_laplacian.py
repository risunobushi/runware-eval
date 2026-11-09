"""Laplacian variance inside a region, relative to the input (1.0 = as sharp)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'sharpness_laplacian',
    'trust': 'deterministic',
    'family': 'signal',
    'kind': 'info',
    'needs': ['reference', 'region'],
    'unit': '× input',
    'direction': 'higher',
    'description': 'Laplacian variance inside a region, relative to the input (1.0 = as sharp).',
}


def compute(p, opt):
    def sharp(rgb, m):
        g = cv2.cvtColor((rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
        return cv2.Laplacian(g, cv2.CV_64F)[erode(m)].var()
    spec = opt.get("region")
    return {"value": float(sharp(p.rgb_out, p.region(spec, "out")) / sharp(p.rgb_in, p.region(spec)))}
