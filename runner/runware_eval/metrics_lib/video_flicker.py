"""Brightness flicker in a video: frame-to-frame jumps in lightness that a smooth change would not have."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_flicker',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': 'L*',
    'direction': 'lower',
    'description': 'Brightness flicker in a video: frame-to-frame jumps in lightness that a smooth change would not have.',
}


def compute(pair, opt):
    """Lightness is averaged over a coarse grid of cells per frame; for each cell, the second difference
    over time (L[t+1] - 2 L[t] + L[t-1]) is zero for steady light and for smooth fades, and large when
    brightness jumps back and forth. `value` is the mean absolute second difference over cells and time."""
    v = video(pair)
    n = int(opt.get("grid", 8))
    L = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2LAB)[..., 0], (n, n), interpolation=cv2.INTER_AREA)
                  for f in v["frames"]]).astype(np.float32) * (100.0 / 255.0)
    if len(L) < 3:
        return {"value": float("nan")}
    d2 = np.abs(L[2:] - 2 * L[1:-1] + L[:-2])
    return {"value": float(d2.mean()), "worst_frame": float(d2.mean(axis=(1, 2)).max())}
