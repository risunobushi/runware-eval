# Choosing metrics

What is implemented is listed in `metric-catalog.md`, generated from the metric files (the source of
truth). This file is guidance: which metric answers which question. Every metric below is implemented
in the runner; what is missing, a bench writes in its `metrics/` folder. Select by dimension, filter by
`needs`, order by `trust`, and pair each primary metric with a cross-check from a different `family`.

- `trust`: `deterministic` > `learned` > `judge` > `human`
- `needs`: `reference` (the input or a target image), `region` (a mask), `text` (expected copy),
  `identity_ref` (reference face or product), `brief` (the prompt or goal), `labels` (user ratings)
- `runs_on`: `local_cpu`, or `runware_vlm` (vision-capable model called through Runware
  `textInference`)

> **Limits.** The "default" column below is a reference for reading a value, not something to write into
> `bench.yaml`. Numeric checks get their limit from the bench's first full run (typical recipe plus a
> margin, frozen in `limits.yaml`; see `bench-format.md`). Write a limit by hand only when the brief
> states one.

## Deviation — did it change what it should not?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `deltaE2000_region` | colorimetric | deterministic | reference, region | local_cpu | ΔE, lower | mean ≤ 1.0 (invisible), p95 ≤ 2.0 |
| `ssim_region` | structural | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 |

Notes: erode the region mask slightly (about 0.15% of the long side) so anti-aliased edges do not
count as change. Report mean and p95, not just the mean.

## Pixel shift — did anything move, warp, crop or resize?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `size_aspect` | geometric | deterministic | reference | local_cpu | px, exact | identical size |
| `phase_correlation` | geometric | deterministic | reference | local_cpu | px offset, lower | ≤ 1 px |
| `mask_iou` | geometric | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 |

Measure pixel shift before deviation: a 2 px misalignment inflates ΔE everywhere along the edges.

## Identity — is it still the same face, product or character?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `vlm_same_object` | judge | judge | identity_ref | runware_vlm | yes/no rate | ≥ 0.9 |
| `keypoint_match` | geometric | deterministic | reference, region | local_cpu | matched share of SIFT points (512 px), higher | info only |

## Text & brand — is the copy and the logo exactly right?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `ocr_cer` | ocr | learned | reference | local_cpu | character error rate of the expected text, lower | ≤ 0.02 |
| `ocr_extra_text` | ocr | learned | reference | local_cpu | words nobody asked for, lower | 0 |
| `detail_similarity` | detail | deterministic | reference, region | local_cpu | NCC of high-pass luminance, higher | ≥ 0.8 |

The OCR checks read the picture with a local OCR model (it ships with the runner; nothing is sent
anywhere). `ocr_cer` looks for the expected text in what was read and reports the share of its
characters that are wrong or missing; text around it does not count. The expected text is `text:` on
the check or on the input (a string or a list); without one it is the text read off the input, so the
check asks "did the copy survive?". `ocr_extra_text` counts the words that are neither in the input nor
in the expected text: models often add taglines, credits or gibberish nobody asked for. Both take
`region:` to read one part of the picture only, and both list what they found next to the value.

Limits to say out loud: the OCR model reads printed Latin letters, digits and Chinese. It missed
embossed, tone-on-tone lettering on a leather patch completely, and small print in a large frame (name
the region, so the crop is read). It does not keep spaces reliably, so the comparison ignores spaces and
case (`case: true` keeps case). When it reads nothing in the input and no `text:` is given, `ocr_cer`
shows as an error for that input, not as a pass. Keep `detail_similarity` next to it for logos, and a
judge question for lettering no OCR reads.

## Prompt adherence — did it do what the brief asked?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `vlm_checklist` | judge | judge | brief | runware_vlm | share of yes answers, higher | ≥ 0.9 |

`vlm_checklist`: turn the brief into 3–8 yes/no questions, show them to the user, then ask a vision
model each question per output. Use a **panel of judges from different providers** (Runware hosts
several) and report agreement between them.

Vision-model metrics (`vlm_*`) send image 1 (original, or a crop of `region`) and image 2 (output,
same crop) to every judge in `judges`, plus any `refs: [<media name>]` as images 3, 4, … Use `refs`
whenever a question says "as in the reference". Default panel: Gemini 3.1 Flash-Lite, Claude Haiku 4.5,
GPT-5.4 nano. In testing, Gemini scored rubrics far more generously than Claude or GPT, which
is why a rubric score places recipes and is never a pass/fail check by itself. Measured cost of one combined call: Flash-Lite $0.0010, GPT-5.4 nano $0.0007, Claude Haiku 4.5 $0.0038.

A measurable instruction that no library metric covers gets a metric written for the bench (a file in
its `metrics/` folder; see "To write a metric" in the skill). Benches so far wrote: where the key light
falls (left against right half of the product), contrast gain, backdrop lightness, a cast shadow beside
the product. Example: a contact shadow is the lightness drop (ΔL*) in a band directly below the product,
compared with the backdrop. "Too dark" is a failure as well as "none", so such a metric reports the
distance from the wanted range, not the raw drop.

## Aesthetics — is it good?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `vlm_rubric` | judge | judge | brief | runware_vlm | 1–5, higher | no limit |

Aesthetics is the user's call: the user labels outputs good or bad, blind, in the report, and
compares pairs. `calibrate` shows how often each limit agreed with them (AUC for measurements without a
limit) and turns the pair choices into the user's own ranking of the recipes (Bradley-Terry). Below an
AUC of about 0.7, go by that ranking instead of the measurement. About 20 labels (at least 5 good, 5
bad) make the figures dependable.

## Technical quality — is it clean?

| id | family | trust | needs | runs_on | unit / direction | default limit |
|---|---|---|---|---|---|---|
| `sharpness_laplacian` | signal | deterministic | — | local_cpu | variance, higher | relative to input |
| `seam_jump` | compositing | deterministic | reference, region | local_cpu | border brightness step minus the original's, lower | ≤ 10 |

## Calibration notes (relight bench, bag)

- `detail_similarity` (logo): synthetic relight with intact letters 0.995 (0.898 with noise); garbled
  lettering 0.40–0.62; reinvented patches ≈ 0. It survives lighting changes, so it is the logo check
  for relighting. Not measured for recipes that copy the region back (a pass would be by construction).
- `seam_jump` (logo): pasted patches 18–28; everything else −1.7 to 6.4.
- `keypoint_match`: rejected as an identity check for relighting. It tracked how much the light
  changed (same bag under strong light 0.05; redrawn bag 0.33; synthetic relight 0.74). Info only.

## The judge funnel

Judges see only outputs that fail at most `judgeWhen.maxFailedChecks` pixel checks (default 1),
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
video checks read the whole clip at 8 frames per second, longest side 384 px. **Five sample frames**,
spread evenly from the first to the last, are kept at full size: the run buys a product outline for
each (background removal, about 0.0006 USD a frame), the product checks read them, and the judges see
the first, middle and last one. The report embeds a small preview of each clip and a first / middle /
last frame strip, plays two recipes' clips side by side on one clock, and draws every measurement that
has a value per frame over time, one line per recipe.

| id | unit | notes |
|---|---|---|
| `video_motion` | % of diagonal / s | mean optical flow; a still clip scores about 0. `min` rejects clips that barely move, `max` ones that move too much |
| `video_scene_hold` | histogram distance | largest change in the picture's colour make-up within half a second: a cut or a swapped set scores high, motion inside one scene low (real clips: 0.02-0.19 held, 0.60-0.85 swapped) |
| `video_frozen_frames` | share of clip | how much of the clip does not change at all; also the longest frozen stretch and when the picture first moves |
| `video_texture_stability` | L* residual | what is left after moving each frame onto the next along the measured motion: boiling or morphing surfaces score high. Cuts and newly revealed sides raise it too, so read it next to `video_scene_hold` |
| `video_flicker` | L* | brightness jumping back and forth between frames; smooth fades do not count |
| `video_color_drift` | ΔE2000 | how far the average colour moves from the first frame; ignores where things are, so motion is not drift |
| `video_sharpness_hold` | × first frame | sharpness of the last quarter vs the first frame; fast motion lowers it honestly, read it next to `video_motion` |
| `video_letterbox` | share of frame | black bars that stay for the whole clip (fixed-shape models pad other shapes). The runner leaves bars out before every other check; set `max: 0` if the clip must have none |
| `video_duration` | s | also reports frame rate and size; limit it when a model has fixed duration steps |

Product checks, on the five sample frames and their outlines:

| id | unit | notes |
|---|---|---|
| `video_outline_hold` | IoU, higher | lowest overlap between the product's outline in a sample frame and in the input. As it is, for clips where the product should stay put (a relight, a locked-off shot). `align: true` first moves and scales each outline onto the input's bounding box, so only the shape counts: a push-in passes, a product that changes shape does not. A turning product changes shape honestly: do not limit it on an orbit |
| `video_product_area` | × input area | smallest area of the product over the clip relative to the input (`largest` and `pieces` too). Near 0: it left the frame or dissolved. No better direction, so no limit is set from results: write both sides (`min: 0.5, max: 2`) from what the brief allows |
| `video_product_drift` | histogram distance, lower | is it still the same product later on? The product's colour make-up inside its own outline, each sample frame against the input (0 = same, 1 = nothing in common); `first` is the floor a plain re-encode scores. It follows the product wherever it moves. `ignore_lightness: true` for briefs that change the light. It does not see shape or lettering |
| `mask_iou`, `phase_correlation`, `bbox_aspect` | | the image outline checks now run on a video's first frame, with that frame's outline |
| `vlm_same_object`, `vlm_checklist`, `vlm_rubric` | | on a video the judges get the input and the first, middle and last frame, and are asked about "the video": a question holds only if it holds in every frame shown. A check with a `region` still compares that region of the first frame only (a region is where it was in the input) |

Limits to say out loud: the product checks read five frames, not every frame, so a fault that comes
and goes between them is only caught by the frame-wide checks. A product that turns shows other
sides: its outline, area and colours change honestly, so limits for an orbit must be loose and the
judges carry "is it the same product". Lettering in later frames has no pixel check (the logo moves):
ask the judges. Limits for the video checks are set from the first full run like any other; check them against your
labels. `video: { masks: false }` in bench.yaml skips the outlines; the product checks then show as not run.

## Upscaled pictures (`upscale`)

An upscaled picture is compared with its input twice: shrunk back to the input's size by the image
checks above ("is it still the same picture?"), and at its own size by the upscale checks ("did it
gain anything?").

| id | unit | notes |
|---|---|---|
| `upscale_factor` | × input | delivered width and height over the input's. Limit: `min` just under the factor asked for |
| `upscale_detail_gain` | × plain resize | fine detail at the output's own size against the input enlarged by plain resampling; 1.0 = no more than a resize. It counts invented texture as detail: in a full run the two upscalers with the highest gain (18 and 42) were the two furthest from the real photo. Never a limit on its own |
| `upscale_truth_ssim` | SSIM, higher | needs ground truth: give each input an `original:` (the full-size picture) and use that picture shrunk as the input. Compares the result with the original at the original's size, and reports what a plain resize scores (`plain_resize`, `over_plain_resize`). The only check that tells recovered detail from invented detail |
| `upscale_truth_psnr` | dB, higher | the same comparison as pixel error. Stricter than SSIM about texture that is sharp but not the original's |
| `size_aspect`, `phase_correlation` | | run these first. Seen on Runware: a 1366x1800 input came back as 2688x3584 from two upscalers (the input is cut to a multiple of 64 before upscaling), which fails both and drags every fidelity value down |
| `ssim_region`, `deltaE2000_region` | | fidelity at the input's size, inside a region. Upscalers that redraw texture lower SSIM without changing what the product is: check the limit against your labels |

Ground truth is the baseline to build an upscale bench on: take full-size pictures of the kind you will
upscale, shrink them by the factor under test (`original:` on the input points at the full-size one),
and upscale the small ones. Limits to say out loud, from a full run of eight upscalers on three product
photos: (1) on inputs shrunk by plain resampling, a plain resize back is hard to beat on SSIM and PSNR
(only one of eight upscalers did, by 0.01 to 0.02 SSIM); both reward a soft but faithful picture over a
crisp one, so they rank faithfulness, not how good it looks: add a `vlm_rubric` or labels for that.
(2) Real small pictures are degraded in other ways than a clean shrink (compression, noise); shrink
them the way yours were made if you know it. (3) Several upscalers do not return exactly the size
asked: inputs whose sides are not multiples of 64 came back cut (two models) or resized (two others),
one model returned 1.91x to 2.06x; `upscale_factor`, `size_aspect` and `phase_correlation` catch it.
(4) Prices grow with the input's size and were up to 13x the listed top price on a 1366x1800 input:
smoke one large input before a full round.

## Cut-outs and masks (`removeBackground`, `imageMasking`)

The output is an outline: the alpha channel of a cut-out, or the mask itself. Every check compares it
with a reference outline of the same input (`regions`, named by `region:` on the check), at the
input's size. No vision judge is needed for the outline; ask judges only about what an outline cannot
say (a halo's colour, a missing shadow).

| id | unit | notes |
|---|---|---|
| `mask_iou` | 0–1, higher | overlap with the reference. Forgiving on big shapes: a lost strap barely moves it |
| `mask_missing` | share of the reference, lower | how much of the subject was cut away. Tested on a bag: 0.011 for a clean cut, 0.112 for one that lost the strap |
| `mask_extra` | share of the reference, lower | background kept or selected. A cut-out delivered without transparency keeps the whole frame |
| `mask_boundary_px` | px, lower | mean distance between the two outlines (also p95): a ragged or shifted edge. 0.5 px for the clean cut, 158 px for the lost strap |
| `alpha_edge_softness` | px | width of the semi-transparent edge of a cut-out, counted near the outline only: about 0 is a hard edge, 1–3 clean anti-aliasing, more a soft matte or a halo. No better direction: do not limit it without labels |
| `alpha_opacity` | mean alpha, higher | how solid the cut-out is inside the reference region, away from the edge. Seen: 1.000 and 0.996 for most removers, 0.980 for one that left the whole subject faintly see-through. Limit: `min: 0.99` |
| `size_kept` | × input, higher | delivered size over the input's. Seen: every background remover returned a 1920x2560 input at 1536x2048 (0.8). Limit: `min: 1` when the cut-out must keep the photo's resolution |
| `mask_pieces` | pieces, lower | separate pieces of the cut-out or mask (no reference needed): one product is one piece; more means stray islands or a subject cut apart. Also `holes` and `largest_share` |
| `mask_selected_share` | share of the frame | how much the cut-out keeps or the mask selects (no reference needed). 0 = nothing was found, 1 = nothing was removed |
| `mask_box_fill` | share of its box | 1.0 = the mask is a plain rectangle. Seen: the YOLO face, hand and "person seg" masks are all boxes (0.96 to 1.0); the MediaPipe meshes are traced shapes (0.3 to 0.6). Limit: `max: 0.95` when an outline is needed |
| `mask_inside` | share of the mask, higher | how much of the mask lies inside a region: for a mask of a part (face, hands), checked against the outline of the whole person. Not a substitute for a reference of the part itself |

Limits to say out loud: the reference outline decides everything, so a reference made by a model
favours that model and its relatives (in a full run of eleven removers the reference's own model scored
exactly 1.000 on three of four inputs, and so did a second listed model that returned the same outline).
A mask of a part needs a reference of that part: give the input a box (`regions: { face: { box: [...] } }`)
and name it on the check; against the whole person, overlap and missing say nothing. Limits are the same
for every input, so "an empty mask on a photo without a person" cannot be a limit next to "a full mask on
a photo with one": bench the two kinds of input separately, or read `mask_selected_share` per input. Masking models on Runware detect faces, hands and people; on
anything else they return a box (seen on a bag: `mask_extra` 2.7).

## Vector files (`vectorize`)

The runner renders the SVG on white at the input's width (the renderer ships with the runner), so the
image checks above compare the drawing with the input. The file checks read the SVG itself:

| id | unit | notes |
|---|---|---|
| `svg_images` | bitmaps | embedded pictures. Above 0 it is a picture in an SVG wrapper: limit: `max: 0` |
| `svg_shapes` | shapes | paths, rectangles, circles ... Fewer is easier to edit |
| `svg_nodes` | nodes | anchor points over all shapes: how heavy the drawing is |
| `svg_colours` | colours | distinct fills and strokes; hundreds means gradients traced into steps |
| `svg_file_kb` | KB | file size |

Tested on a product photo: two vectorizers both looked like the input (SSIM 0.96 and 0.97) while one
used 146 shapes and 2,527 nodes and the other 537 and 11,032: the file checks are what tells them
apart. On a flat four-colour logo two of three vectorizers returned exactly four colours and 18
shapes; the third returned 8 colours (fringes traced as shapes): for logos, compare `svg_colours` with
the number of colours you drew. `phase_correlation` does not run on vector outputs (no product outline is
made for them). All three traced the backdrop as a shape: none returned a transparent background.
An SVG the renderer cannot open is kept, its file checks run, and its picture checks show as
*not run*.

## Text (`caption`, `textInference`)

The output is the text. Deterministic checks read it directly; everything about meaning goes to the
judges.

| id | unit | notes |
|---|---|---|
| `text_words` | words | length; write both sides (`min`, `max`) when the brief sets one |
| `text_sentences` | sentences | for "one sentence" or "at most three": limit: `max` |
| `text_terms` | share found, higher | required words, from `terms:` on the check or on the input |
| `text_banned` | terms found, lower | forbidden words (filler, claims you may not make), from `banned:`. Limit: `max: 0` |
| `text_regex` | 1 / 0 | `pattern:` found in the text: a fixed format |
| `text_json` | 1 / 0 | valid JSON, with every key in `keys:`. A Markdown code fence around it is forgiven and reported (`fenced`); `strict: true` reads the answer as delivered, the way `json.loads` would. Seen: one of five text models fenced every answer, another two of three |
| `text_reasoning_leak` | words, lower | reasoning the model left in its answer (`<think>` blocks). Seen: one of five models, 250 words per answer. The other text checks read the answer without it; limit this one with `max: 0` if you use answers as delivered |
| `text_reference_f1` | F1, higher | shared words with the input's `reference:` text. It rewards the same words, not the same meaning: never the only content check |
| `text_truncated` | 1 / 0 | cut off by the token limit (`textInference` only). Limit: `max: 0` |
| `text_output_tokens` | tokens, lower | what the answer cost to write (`textInference` with `includeUsage: true`) |

`field: <name>` on `text_words`, `text_sentences`, `text_terms`, `text_banned`, `text_regex` and
`text_reference_f1` reads one field of a JSON answer instead of the whole text
(`{ id: text_words, field: title, max: 8 }`). Use it for anything countable: do not ask a judge whether
a title has at most 8 words.

`vlm_checklist` and `vlm_rubric` work on text: the judges get the input (the picture for a caption,
the text for a text input), the `task` from bench.yaml and the answer, and questions are asked about
"the TEXT" ("Is everything the TEXT says visible in image 1?", "Is every fact in the TEXT supported by
the INPUT?"). Set `judgeWhen: { maxFailedChecks: 99 }` when the text checks are few, so every answer
is judged. Tested on a product photo: two captioners both called a nylon bag "leather"; no word check
caught it, the checklist did (and the three judges disagreed on it: read `agreement`).

What a full run showed about captions (four captioners, four photos, three draws): none passed a
two-question checklist on any photo; all three language models called a nylon bag leather; the CLIP
interrogator returns a list of tags, with invented artist and person names, not a sentence. Answers were
the same on every draw for 11 of 16 model and photo pairs, and each call was billed: use `draws: 1`
for captioners. The report now says when every draw of a recipe came back as the very same file.

Limits to say out loud: picture checks do not run on text, and text checks do not run on pictures
(both show as *not run*). There are no controls for a text input. The judges are text models
themselves: do not let a model under test sit on the panel that judges it (set `judges:`); the report
warns when one does.

## Ops — always on

| id | unit | source |
|---|---|---|
| `cost_usd` | USD per output | `includeCost: true` on every task |
| `latency_s` | seconds | runner timing |
| `failure_rate` | share | runner |
