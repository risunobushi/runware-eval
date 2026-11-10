"""Render adapter for video outputs: turn a clip into frames, so image and video checks can run.

Like the 3D adapter, it makes a video look like something the rest of the runner already knows:
- the first frame at full size is the output image that the image checks compare with the input
  (for image-to-video, the first frame should be the input);
- a short, small frame sequence (8 frames per second, longest side 384 px) is what the video checks
  read through `metric_api.video(pair)`;
- a strip of the first, middle and last frame and a small H.264 preview go into the report.

Black bars: a model with fixed output shapes (16:9 or 9:16 only) pads an input of another shape.
The adapter finds bars that stay black for the whole clip and leaves them out of the first frame and
the frame sequence, so the picture is compared with the input like any other; the bars themselves are
reported (`bars`, and the `video_letterbox` check). The strip and the preview show the file as delivered.

ffmpeg comes from the `imageio-ffmpeg` wheel (a static binary installed by uv), so nothing has to be
installed on the machine.
"""
import os
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image

VIDEO_EXT = (".mp4", ".webm", ".mov", ".m4v")
ANALYSIS_FPS = 8
ANALYSIS_SIDE = 384
ADAPTER = 2  # raise when prepare() changes what it writes, so cached render facts are rebuilt


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def _decode(path, fps=ANALYSIS_FPS):
    """Yield (meta, frame) with frames as uint8 RGB arrays at native size, resampled to `fps`."""
    gen = imageio_ffmpeg.read_frames(path, pix_fmt="rgb24", output_params=["-vf", f"fps={fps}"])
    meta = next(gen)
    w, h = meta["size"]
    try:
        for raw in gen:
            yield meta, np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    finally:
        gen.close()


def _small(frame, side=ANALYSIS_SIDE):
    h, w = frame.shape[:2]
    s = side / max(w, h)
    return frame if s >= 1 else cv2.resize(frame, (max(1, round(w * s)), max(1, round(h * s))),
                                           interpolation=cv2.INTER_AREA)


def find_bars(small_frames, level=20, min_share=0.02):
    """Bars that are black in every frame, as shares of the frame: (top, bottom, left, right).
    A dark scene is not a bar: a row or column counts only if it never gets brighter than `level`
    at any time, and a bar must cover at least `min_share` of the side."""
    peak = np.max(np.stack(small_frames), axis=(0, 3))  # brightest value each pixel ever takes
    rows, cols = peak.max(axis=1) <= level, peak.max(axis=0) <= level

    def run(flags):
        n = 0
        while n < len(flags) and flags[n]:
            n += 1
        share = n / len(flags)
        return share if min_share <= share < 0.45 else 0.0
    return run(rows), run(rows[::-1]), run(cols), run(cols[::-1])


def _crop(frame, bars):
    t, b, l, r = bars
    h, w = frame.shape[:2]
    return frame[round(t * h):h - round(b * h), round(l * w):w - round(r * w)]


def frames(path, fps=ANALYSIS_FPS, side=ANALYSIS_SIDE, bars=None):
    """The analysis sequence: (N, h, w, 3) uint8, `fps` frames per second, longest side `side`,
    with constant black bars left out when `bars` (from `prepare`) says there are any."""
    return np.stack([_small(_crop(f, bars) if bars and any(bars) else f, side) for _, f in _decode(path, fps)])


def prepare(path, first_png, strip_jpg, preview_mp4):
    """Write the first frame, a first/middle/last strip and a small preview. Returns the clip's facts."""
    meta, first, mid, last, n, mid_at, small = None, None, None, None, 0, 0, []
    for meta, f in _decode(path):
        small.append(_small(f, 192))
        if n == 0:
            first = f
            mid_at = int(round((meta.get("duration") or 0) * ANALYSIS_FPS)) // 2
        if n <= mid_at:
            mid = f
        last = f
        n += 1
    if not n:
        raise ValueError(f"No frames could be read from {os.path.basename(path)}")
    bars = find_bars(small)
    Image.fromarray(_crop(first, bars)).save(first_png)
    strip = np.concatenate([_small(x, 480) for x in (first, mid, last)], axis=1)
    Image.fromarray(strip).save(strip_jpg, quality=85)
    w, h = meta["size"]
    try:
        frames_native, secs = imageio_ffmpeg.count_frames_and_secs(path)
    except Exception:  # noqa: BLE001  container without a readable frame count
        frames_native, secs = None, meta.get("duration")
    preview = _preview(path, preview_mp4)
    ch, cw = _crop(first, bars).shape[:2]
    return {"adapter": ADAPTER, "bars": [round(x, 4) for x in bars], "content_width": cw, "content_height": ch,
            "bars_share": round(1 - (cw * ch) / (w * h), 4),
            "width": w, "height": h, "native_fps": float(meta.get("fps") or 0), "duration": float(secs or 0),
            "native_frames": frames_native, "analysis_fps": ANALYSIS_FPS, "analysis_frames": n,
            "file_mb": os.path.getsize(path) / 1e6, "preview": bool(preview)}


def _preview(path, out_mp4, height=480):
    """A small silent H.264 copy for the report (about 300-600 KB for 5 s). None if encoding fails."""
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", path, "-an",
           "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4]
    res = subprocess.run(cmd, capture_output=True)
    return out_mp4 if res.returncode == 0 and os.path.exists(out_mp4) else None
