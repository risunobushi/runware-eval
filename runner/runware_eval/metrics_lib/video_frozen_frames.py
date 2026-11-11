"""Share of a video in which the picture does not change at all (0 = always changing, 1 = a still image)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {
    'id': 'video_frozen_frames',
    'trust': 'deterministic',
    'family': 'video',
    'kind': 'info',
    'needs': ['video'],
    'unit': 'share of clip',
    'direction': 'lower',
    'tolerance': 0.02,  # smallest difference that counts (margin of a limit set from results)
    'description': 'Share of a video in which the picture does not change at all (0 = always changing, 1 = a still image).',
}


def compute(pair, opt):
    """A step between two analysis frames counts as frozen when fewer than `area` of the pixels (default
    0.2%) changed by more than `level` (default 6 of 255: above compression noise). Counting changed
    pixels, not the average change, keeps a small subject moving on a plain backdrop from reading as
    frozen. `value` is the share of frozen steps; `longest_s` is the longest frozen stretch; `starts_at_s` is
    when the picture first changes (a clip that starts late)."""
    v = video(pair)
    g = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32) for f in v["frames"]]
    if len(g) < 2:
        return {"value": float("nan")}
    level, area = float(opt.get("level", 6)), float(opt.get("area", 0.002))
    frozen = np.array([float((np.abs(a - b) > level).mean()) for a, b in zip(g, g[1:])]) < area
    longest = run = 0
    for x in frozen:
        run = run + 1 if x else 0
        longest = max(longest, run)
    moving = np.nonzero(~frozen)[0]
    fps = v["analysis_fps"]
    return {"value": float(frozen.mean()), "longest_s": float(longest / fps),
            "starts_at_s": float(moving[0] / fps) if len(moving) else float(len(frozen) / fps)}
