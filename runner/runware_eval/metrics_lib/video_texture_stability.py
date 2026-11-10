"""Do surfaces hold still as they move? What is left when each frame is moved onto the next along the measured motion (lower = steadier)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_texture_stability',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': 'L* residual',
    'direction': 'lower',
    'description': 'Do surfaces hold still as they move? What is left when each frame is moved onto the next along the measured motion (lower = steadier).',
}


def compute(pair, opt):
    """Warping error. Optical flow says where each pixel went; the next frame is pulled back along it and
    compared with the current one. Real motion is explained by the flow and leaves little behind;
    texture that boils, shimmers or morphs is not, and stays as a residual. Each frame's mean
    lightness is removed first, which takes out most of a plain brightness change; strong flicker and
    cuts still raise it, so read it next to `video_flicker` and `video_scene_hold`. `value` is the
    mean absolute residual in L* over the clip; `worst_frame` is the worst moment. Newly revealed
    areas (a side coming into view) also leave a residual, so fast turns score somewhat higher."""
    flows, g = video_flow(pair)
    if not flows:
        return {"value": float("nan")}
    h, w = g[0].shape
    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    L = [x.astype(np.float32) * (100.0 / 255.0) for x in g]
    per = []
    for i, flow in enumerate(flows):
        back = cv2.remap(L[i + 1], xx + flow[..., 0], yy + flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        per.append(float(np.abs((back - back.mean()) - (L[i] - L[i].mean())).mean()))
    return {"value": float(np.mean(per)), "worst_frame": float(np.max(per))}
