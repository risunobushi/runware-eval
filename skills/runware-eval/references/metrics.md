# Metric registry

Each metric is a card. Select by `dimension`, filter by `needs`, order by `trust`, and pair each
primary metric with a cross-check from a different `family`.

- `trust`: `deterministic` > `learned` > `judge` > `human`
- `needs`: `reference` (the input or a target image), `region` (a mask), `text` (expected copy),
  `identity_ref` (reference face or product), `brief` (the prompt or goal), `labels` (user ratings)
- `runs_on`: `local_cpu`, `serverless_gpu` (Runware Serverless metric worker), `runware_vlm`
  (vision-capable model called through Runware `textInference`)
- `status`: `ready` (implemented in the runner) or `planned` (selectable, flagged as unavailable)

## Deviation — did it change what it should not?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `deltaE2000_region` | colorimetric | deterministic | reference, region | local_cpu | ΔE, lower | mean ≤ 1.0 (invisible), p95 ≤ 2.0 | ready |
| `ssim_region` | structural | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 | ready |
| `lpips_region` | perceptual | learned | reference, region | serverless_gpu | 0–1, lower | ≤ 0.05 | planned |
| `dino_similarity` | semantic | learned | reference | serverless_gpu | cosine, higher | ≥ 0.95 | planned |

Notes: erode the region mask slightly (about 0.15% of the long side) so anti-aliased edges do not
count as change. Report mean and p95, not just the mean.

## Pixel shift — did anything move, warp, crop or resize?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `size_aspect` | geometric | deterministic | reference | local_cpu | px, exact | identical size | ready |
| `phase_correlation` | geometric | deterministic | reference | local_cpu | px offset, lower | ≤ 1 px | ready |
| `mask_iou` | geometric | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.98 | ready |
| `optical_flow_region` | motion | learned | reference, region | serverless_gpu | px, lower | p95 ≤ 1 px | planned |

Measure pixel shift before deviation: a 2 px misalignment inflates ΔE everywhere along the edges.

## Identity — is it still the same face, product or character?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `dino_similarity_crop` | semantic | learned | identity_ref, region | serverless_gpu | cosine, higher | ≥ 0.90 | planned |
| `arcface` | face | learned | identity_ref | serverless_gpu | cosine, higher | ≥ 0.6 | planned |
| `vlm_same_object` | judge | judge | identity_ref | runware_vlm | yes/no rate | ≥ 0.9 | ready |

## Text & brand — is the copy and the logo exactly right?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `ocr_cer` | ocr | deterministic | text | local_cpu | character error rate, lower | ≤ 0.02 | planned |
| `logo_template_match` | geometric | deterministic | reference, region | local_cpu | 0–1, higher | ≥ 0.9 | planned |
| `ocr_extra_text` | ocr | deterministic | text | local_cpu | count of unexpected words, lower | user-set | planned |

Models often add text nobody asked for (taglines, credits, gibberish). Score `ocr_cer` on whether
the expected string is present, and report `ocr_extra_text` separately. Ask the user whether extra
text is a failure (a gate) or acceptable.

## Prompt adherence — did it do what the brief asked?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `vlm_checklist` | judge | judge | brief | runware_vlm | share of yes answers, higher | ≥ 0.9 | ready |
| `task_specific` | varies | deterministic | varies | local_cpu | varies | user-set | ready |

`vlm_checklist`: turn the brief into 3–8 yes/no questions, show them to the user, then ask a vision
model each question per output. Use a **panel of judges from different providers** (Runware hosts
several) and report agreement between them.

Vision-model metrics (`vlm_*`) send image 1 (original, or a crop of `region`) and image 2 (output,
same crop) to every judge in `judges`, plus any `refs: [<media name>]` as images 3, 4, … Use `refs`
whenever a question says "as in the reference". Default panel: one model each from Google,
Anthropic and OpenAI. In testing, Gemini scored rubrics far more generously than Claude or GPT, which
is why rubrics are rank-only until calibrated. Cost is about $0.004–0.005 per judge call.

`task_specific` covers measurable instructions. Implemented names: `lr_lighting_shift`,
`shading_contrast`, `backdrop_lightness` (gate with `abs_max`) and `contact_shadow`. Example: a contact shadow is the lightness drop
(ΔL*) in a band directly below the product, compared with the backdrop. Gate it from both sides
(e.g. 8 ≤ ΔL* ≤ 30), because "too dark" is also a failure.

## Aesthetics — is it good?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `aesthetic_predictor` | learned_aesthetic | learned | — | serverless_gpu | score, higher | rank only | planned |
| `vlm_rubric` | judge | judge | brief | runware_vlm | 1–5, higher | rank only | ready |
| `pairwise_human` | human | human | labels | local_cpu | Bradley-Terry score | rank only | planned |

Aesthetics is never a gate until calibrated. The user labels 5–10 outputs good or bad; the report
shows how often each metric agreed with them. If agreement is below about 70%, rank by blind
pairwise human comparison instead.

## Technical quality — is it clean?

| id | family | trust | needs | runs_on | unit / direction | default gate | status |
|---|---|---|---|---|---|---|---|
| `sharpness_laplacian` | signal | deterministic | — | local_cpu | variance, higher | relative to input | ready |
| `banding` | signal | deterministic | — | local_cpu | score, lower | user-set | planned |
| `niqe` | no_reference_iqa | learned | — | local_cpu | score, lower | rank only | planned |

## Ops — always on

| id | unit | source |
|---|---|---|
| `cost_usd` | USD per output | `includeCost: true` on every task |
| `latency_s` | seconds | runner timing |
| `failure_rate` | share | runner |
