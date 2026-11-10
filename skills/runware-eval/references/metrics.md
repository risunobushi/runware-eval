# Choosing metrics

What is implemented is listed in `metric-catalog.md`, generated from the metric files (the source of
truth). This file is guidance: which metric answers which question, and ideas that are not built
yet (marked `planned`; a bench can implement one in its `metrics/` folder). Select by dimension,
filter by `needs`, order by `trust`, and pair each primary metric with a cross-check from a
different `family`.

- `trust`: `deterministic` > `learned` > `judge` > `human`
- `needs`: `reference` (the input or a target image), `region` (a mask), `text` (expected copy),
  `identity_ref` (reference face or product), `brief` (the prompt or goal), `labels` (user ratings)
- `runs_on`: `local_cpu`, `serverless_gpu` (Runware Serverless metric worker), `runware_vlm`
  (vision-capable model called through Runware `textInference`)
- `status`: `ready` (implemented in the runner) or `planned` (selectable, flagged as unavailable)

## Deviation — did it change what it should not?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `deltaE2000_region` | colorimetric | deterministic | reference, region | local_cpu | ΔE, lower | mean ≤ 1.0 (invisible), p95 ≤ 2.0 | ready |
| `ssim_region` | structural | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 | ready |
| `lpips_region` | perceptual | learned | reference, region | serverless_gpu | 0–1, lower | ≤ 0.05 | planned |
| `dino_similarity` | semantic | learned | reference | serverless_gpu | cosine, higher | ≥ 0.95 | planned |

Notes: erode the region mask slightly (about 0.15% of the long side) so anti-aliased edges do not
count as change. Report mean and p95, not just the mean.

## Pixel shift — did anything move, warp, crop or resize?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `size_aspect` | geometric | deterministic | reference | local_cpu | px, exact | identical size | ready |
| `phase_correlation` | geometric | deterministic | reference | local_cpu | px offset, lower | ≤ 1 px | ready |
| `mask_iou` | geometric | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 | ready |
| `optical_flow_region` | motion | learned | reference, region | serverless_gpu | px, lower | p95 ≤ 1 px | planned |

Measure pixel shift before deviation: a 2 px misalignment inflates ΔE everywhere along the edges.

## Identity — is it still the same face, product or character?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `dino_similarity_crop` | semantic | learned | identity_ref, region | serverless_gpu | cosine, higher | ≥ 0.90 | planned |
| `arcface` | face | learned | identity_ref | serverless_gpu | cosine, higher | ≥ 0.6 | planned |
| `vlm_same_object` | judge | judge | identity_ref | runware_vlm | yes/no rate | ≥ 0.9 | ready |
| `keypoint_match` | geometric | deterministic | reference, region | local_cpu | matched share of SIFT points (512 px), higher | info only | ready |

## Text & brand — is the copy and the logo exactly right?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `ocr_cer` | ocr | deterministic | text | local_cpu | character error rate, lower | ≤ 0.02 | planned |
| `detail_similarity` | detail | deterministic | reference, region | local_cpu | NCC of high-pass luminance, higher | ≥ 0.8 | ready |
| `logo_template_match` | geometric | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.9 | planned |
| `ocr_extra_text` | ocr | deterministic | text | local_cpu | count of unexpected words, lower | user-set | planned |

Models often add text nobody asked for (taglines, credits, gibberish). Score `ocr_cer` on whether
the expected string is present, and report `ocr_extra_text` separately. Ask the user whether extra
text is a failure (a gate) or acceptable.

## Prompt adherence — did it do what the brief asked?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `vlm_checklist` | judge | judge | brief | runware_vlm | share of yes answers, higher | ≥ 0.9 | ready |
| `task_specific` | varies | deterministic | varies | local_cpu | varies | user-set | ready |

`vlm_checklist`: turn the brief into 3–8 yes/no questions, show them to the user, then ask a vision
model each question per output. Use a **panel of judges from different providers** (Runware hosts
several) and report agreement between them.

Vision-model metrics (`vlm_*`) send image 1 (original, or a crop of `region`) and image 2 (output,
same crop) to every judge in `judges`, plus any `refs: [<media name>]` as images 3, 4, … Use `refs`
whenever a question says "as in the reference". Default panel: Gemini 3.1 Flash-Lite, Claude Haiku 4.5,
GPT-5.4 nano. In testing, Gemini scored rubrics far more generously than Claude or GPT, which
is why rubrics are rank-only until calibrated. Measured cost of one combined call: Flash-Lite $0.0010, GPT-5.4 nano $0.0007, Claude Haiku 4.5 $0.0038.

`task_specific` covers measurable instructions. Implemented names: `lr_lighting_shift`,
`shading_contrast`, `backdrop_lightness` (gate with `abs_max`) and `contact_shadow`. Example: a contact shadow is the lightness drop
(ΔL*) in a band directly below the product, compared with the backdrop. Gate it from both sides
(e.g. 8 ≤ ΔL* ≤ 30), because "too dark" is also a failure.

## Aesthetics — is it good?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `aesthetic_predictor` | learned_aesthetic | learned | — | serverless_gpu | score, higher | no limit | planned |
| `vlm_rubric` | judge | judge | brief | runware_vlm | 1–5, higher | no limit | ready |
| `pairwise_human` | human | human | labels | labeling page | Bradley-Terry score | no limit | ready (`runware-eval label` / `calibrate`) |

Aesthetics gets no limit until calibrated. The user labels outputs good or bad on the blind
labeling page; `calibrate` shows how often each metric agreed (AUC for rank metrics). Below about
0.7, rank by the blind pairwise human ranking instead. About 20 labels (at least 5 good, 5 bad)
make suggested thresholds dependable.

## Technical quality — is it clean?

| id | family | trust | needs | runs_on | unit / direction | default limit | status |
|---|---|---|---|---|---|---|---|
| `sharpness_laplacian` | signal | deterministic | — | local_cpu | variance, higher | relative to input | ready |
| `seam_jump` | compositing | deterministic | reference, region | local_cpu | border brightness step minus the original's, lower | ≤ 10 | ready |
| `banding` | signal | deterministic | — | local_cpu | score, lower | user-set | planned |
| `niqe` | no_reference_iqa | learned | — | local_cpu | score, lower | no limit | planned |

## Calibration notes (relight bench, bag)

- `detail_similarity` (logo): synthetic relight with intact letters 0.995 (0.898 with noise); garbled
  lettering 0.40–0.62; reinvented patches ≈ 0. It survives lighting changes, so it is the logo check
  for relighting. Not measured for recipes that copy the region back (a pass would be by construction).
- `seam_jump` (logo): pasted patches 18–28; everything else −1.7 to 6.4.
- `keypoint_match`: rejected as an identity gate for relighting. It tracked how much the light
  changed (same bag under strong light 0.05; redrawn bag 0.33; synthetic relight 0.74). Info only.

## The judge funnel

Judges see only outputs that fail at most `judge_when.max_failed_checks` pixel checks (default 1),
and every `vlm_*` question for one output goes into ONE call per judge. Ask judges only what no pixel
check covers (reference leakage, "reads as a real photo", same product overall, aesthetics). On the
bag, 1 of 18 outputs reached the judges: $0.006 instead of $0.88.

## 3D outputs (GLB)

The runner renders every 3D output with a render adapter: it searches 144 views (yaw x elevation x
up-axis) for the silhouette that best matches the input's product mask, renders that view unlit and
places it on the input's canvas, so every image check above applies unchanged. A 4-view turntable
goes into the report. Mesh checks read the file itself:

| id | unit | notes |
|---|---|---|
| `mesh_faces` | faces | triangles in all geometries |
| `mesh_parts` | count | connected components; thousands means a fragmented mesh |
| `mesh_watertight` | 1 / 0 | closed surface (needed for 3D printing, some engines) |
| `mesh_texture_px` | px | largest base-colour texture; 0 = untextured |
| `mesh_file_mb` | MB | GLB size |
| `bbox_aspect` | ratio error | proportions of the silhouette vs the input (images too) |

`detail_similarity` searches small offsets (default ±24 px) before comparing, so re-framed images
and 3D renders are compared fairly. Tested on the bag: no 3D model reproduced the logo lettering
(0.02–0.30 vs 0.995 for intact letters), which matched the crops.

## Video outputs (MP4)

The runner reads every video output with a frame adapter (ffmpeg comes with the runner; nothing to
install). The **first frame** at full size becomes the output image, so every image check above
compares it with the input: for image-to-video that answers "did it start from my image?". The
video checks read the whole clip at 8 frames per second, longest side 384 px. The report embeds a
small preview of each clip and a first / middle / last frame strip.

| id | unit | notes |
|---|---|---|
| `video_motion` | % of diagonal / s | mean optical flow; a still clip scores about 0. `min` rejects clips that barely move, `max` ones that move too much |
| `video_scene_hold` | histogram distance | largest change in the picture's colour make-up within half a second: a cut or a swapped set scores high, motion inside one scene low (real clips: 0.02-0.19 held, 0.60-0.85 swapped) |
| `video_frozen_frames` | share of clip | how much of the clip does not change at all; also the longest frozen stretch and when the picture first moves |
| `video_texture_stability` | L* residual | what is left after moving each frame onto the next along the measured motion: boiling or morphing surfaces score high. Cuts and newly revealed sides raise it too, so read it next to `video_scene_hold` |
| `video_flicker` | L* | brightness jumping back and forth between frames; smooth fades do not count |
| `video_color_drift` | ΔE2000 | how far the average colour moves from the first frame; ignores where things are, so motion is not drift |
| `video_sharpness_hold` | × first frame | sharpness of the last quarter vs the first frame; fast motion lowers it honestly, read it next to `video_motion` |
| `video_letterbox` | share of frame | black bars that stay for the whole clip (fixed-shape models pad other shapes). The runner leaves bars out before every other check; gate with `max: 0` if the clip must have none |
| `video_duration` | s | also reports frame rate and size; gate it when a model has fixed duration steps |

Limits to say out loud: outline checks (`mask_iou`, `phase_correlation`, `bbox_aspect`) are not run
on video, because the output has no product mask of its own. Identity in later frames (is it still
the same product after it turned?) has no pixel check yet: use the frame strip and the labeling
page. Thresholds for the video checks come from synthetic clips; calibrate them on a labeled run.

## Ops — always on

| id | unit | source |
|---|---|---|
| `cost_usd` | USD per output | `includeCost: true` on every task |
| `latency_s` | seconds | runner timing |
| `failure_rate` | share | runner |
