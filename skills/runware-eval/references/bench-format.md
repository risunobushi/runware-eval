# bench.yaml format

One file describes a bench completely. The runner reads it; an agent writes it. Adding a model
later means adding one recipe and re-running. Results are cached by a hash of
(input, recipe, draw), so a re-run only pays for new combinations.

## Fields

| Field | Meaning |
|---|---|
| `goal` | The user's goal in their own words. |
| `task` | Optional. One short sentence shown under the report's headline as "Task: ...". Without it the report uses the first sentence of `goal`. |
| `inputs` | Files or URLs. Each may carry its own `regions` (masks or boxes) and expected `text` (the copy the OCR checks look for). A `.txt` or `.md` file is a text input; `reference`, `terms` and `banned` are per-input facts for the text checks (see "Task types"). |
| `regions` | Named masks: a file path, or `auto:<model AIR>` to generate one on Runware (e.g. BiRefNet). |
| `evaluate` | The dimensions the user chose. Per dimension: `metrics` (ids from `metrics.md`). A metric with a limit (`min`, `max`, `max_px`, `abs_max`, `mean_max`, `p95_max`, `dL_min`, `dL_max`, `aspect_tolerance`) is a pass/fail check; one without is measured only. Both count in the report: recipes that fail a check on the task itself (a metric of kind `change`, or a check with `kind: change`) are listed last; the rest are sorted by failed checks, then by average place on the measurements, then by cost. Numeric checks are written without a limit: the first full run sets it (see "Limits set from the first full run"). |
| `requirements` | What the brief asks, one entry per requirement: `need` (the user's words) and `checks` (labels of the metrics that answer it). `run` stops on a requirement nothing measures (unless it carries `notMeasured: "<why>"`, the user's choice) and warns about one that has no limit; the report lists them. Example: `- { need: "The scene is the reference background", checks: ["Background match", "In the scene (judges)"] }` |
| `budget` | `maxSpend`: the most one full run may spend, in USD. The runner refuses to start above it. Not the Model Router's `maxPrice`, which is a ceiling for one request. |
| `draws` | How many times each recipe runs on each input in the full run (default 3); the smoke round runs one. No seed is sent unless a recipe has `seed: $seed`, so every draw is a new generation: see "Draws and seeds". |
| `passRule` | How draws decide a check, per input: `majority` (default), `all`, `any`. A recipe must pass on every input. |
| `video` | Optional. `video: { masks: false }` stops the run from buying a product outline for five frames of every video output (about 0.003 USD per clip); the product checks on video then show as not run. |
| `maxModels` | Most distinct models the bench may run (e.g. 3 or 5). The runner refuses more. |
| `recipes` | Ids of recipe files to run (or `all`). Each file: `id`, `model` (AIR), `params` (exact schema field names), optional `size` and `mask`, `notes` (every convention translated). |

## Names shared with the Model Router

Where a bench field means the same thing as a field of Runware's Model Router (`model: auto`), it has
the router's name, and the bench's and recipes' own settings follow its camelCase style (`maxModels`, `passRule`,
`recipeDirs`, `judgeWhen`, `maxSide`). Metric options and limits (`mean_max`, `max_px` ...) keep their
own spelling. Shared names: `maxPrice` for a price ceiling on one request in USD (inside `routing`), `routing` and its keys in a router recipe,
and **quality, speed and cost** for what is compared (the checks you choose are the quality; speed is
seconds from request to result; cost is USD per output). `requirements` here is the list of what the
brief asks with the checks that measure it; the router's `routing.requirements` is one sentence it
reads to rule models out.

## Recipes: one file each

Recipes live in `recipes/<id>.yaml` next to `bench.yaml`; `bench.yaml` lists the ones to run by id,
or `recipes: all`. Add shared folders with `recipeDirs: [recipes, ../team-recipes]` (earlier
folders win on duplicate ids). Inline recipe dicts still work; `runware-eval recipes extract` moves
them into files.

```yaml
# recipes/ideogram-precise-low.yaml
id: ideogram-precise-low
model: ideogram:4.5@precise-edit
params:
  inputs: { seedImage: $input, referenceImages: [$lighting_ref] }
  positivePrompt: >-
    Relight this product photo using the lighting of the reference image ...
  settings: { quality: low }
price: 0.03   # USD per output; the estimate and the budget cap use it until a real cost is measured
notes: >-
  Every convention translated for this model.
fingerprint: 8a2fdbe2577bf114   # written by runware-eval; changes when the request changes
```

- **Self-contained:** prompts are written out in the file. A recipe only expects named slots from
  its bench (`$input`, `$seed`, `$mask`, or media such as `$lighting_ref`); the runner says which
  are missing.
- **Fingerprint:** a hash of `taskType`, `model`, `params`, `size` and `mask`. Renaming a recipe or
  editing its notes keeps it; changing the request changes it, and the runner rewrites the line.
- **History:** every result is keyed by fingerprint + content hash of each image sent + draw number. A
  match in any folder under `runs/` (or `--history <folder>`) is copied in instead of paid for again.
- **Sharing:** copy a recipe file into another bench's `recipes/` folder, or point `recipeDirs` at
  a team folder in git.

## Placeholders in recipe `params`

| Placeholder | Becomes |
|---|---|
| `$input` | the input's media URL (uploaded once by the runner, recorded in `media.lock.json`). For a text input (`.txt`, `.md`): its content |
| `$input.width`, `$input.height` | input size, adjusted by the recipe's `size` block |
| `$seed` | the draw's number (1, 2, 3 ...), sent as the seed. Leave it out unless runs must reproduce the same pictures |
| `$prompts.<name>` | a prompt from the top-level `prompts` block |
| `$<name>` | URL of a top-level media entry, e.g. `lighting_ref: { path: refs/light.png }` (a text file: its content, e.g. `style_guide: { path: refs/tone.md }`) |

URLs are sent, not media UUIDs: some provider-backed models fail to fetch a UUID.

## Draws and seeds

A bench runs every recipe `draws` times on every input, so one lucky or unlucky generation does not
decide. **No seed is sent by default.** Without one, every model generates on a random seed, so three
draws are three different outputs, whether or not the model has a seed field; the runner gives each
draw its own cache key, and keeps the seed the model reports in `results.jsonl` (`seed_used`).

A recipe may still pin seeds with `seed: $seed` in its `params` (the draws then use seeds 1, 2, 3): a
later run of the same recipe reproduces the same pictures on models that honour seeds. Use it only when
that is wanted, and only for models whose schema has a seed field. A literal seed (`seed: 42`) makes
every draw the same picture, paid for each time: the report calls out draws that came back as the very
same file.

A recipe's `size` block fits the input to a model's limits: `size: { multiple: 16, maxSide: 2048,
maxMp: 4.19 }`. Check each schema for its own limits and write them here.

## What is checked before a run

**Requirements.** Every entry of `requirements` needs at least one check that exists in `evaluate`.
`estimate` prints the ones that have none (`x nothing measures: ...`) and `run` stops before spending.
The only way past it is the user's choice, written down: `notMeasured: "<why>"` on that requirement.
A requirement whose checks have no limit is printed as a warning (`!`) and does not stop a run.

**Yes/no judge checks** (`vlm_checklist`, `vlm_same_object`) pass or fail without a number: the check
passes when, on every question, more judges say yes than no. A `min` next to one (share of yes answers,
as older benches have) is used instead when present.

**Numeric checks** get their limit from the first full run, not from bench.yaml (see "Limits set from
the first full run" below).

**Parameters.**

`estimate` and `run` validate one request per recipe (and its `then` step) against the model's published
JSON Schema, after every placeholder is filled in:

| Finding | Example | Effect |
|---|---|---|
| a field the model does not have | `widht: 2048` → "did you mean `width`?" | `run` stops before spending |
| a value outside the allowed set or range | `width: 8192`, `outputFormat: TIFF` | `run` stops before spending |
| a field the schema calls required; a rule between fields (`if/then`) | `positivePrompt` missing | printed, the run goes on |
| no schema published for the model | some caption models | printed as not checked |

`model: auto` recipes are not checked (the router has no schema of its own). `--skip-model-check` turns the
check off.

Each run folder also keeps `models.json`: per model, what Runware published on the day (status, version,
prices, every request field with its type, allowed values, range and default). A later run compares and
prints what changed; results carry `model_fp`, the record they were generated under, so the report can mark
the ones from before a change. `run --regenerate-changed` makes those again. Results from before this
record existed carry no stamp and are not marked.

## Limits set from the first full run

A numeric check written without a limit gets one when the first full run is scored:

```
limit  = median of the recipes' medians, moved towards "worse" by the margin
margin = the larger of  the typical spread between draws of one recipe
                        the metric's `tolerance` (smallest difference that counts, in its META)
```

Every recipe counts once. The median is not pulled by one recipe that did nothing or broke, so no
separate step decides which outputs "did the task". The limits are written once to `limits.yaml` next to
`bench.yaml` and never moved again:

```yaml
Bag hue:
  max: 6.67
  from: 'median of 4 recipes (5.46) plus 1.22: the spread between draws (1.22), larger than the smallest difference that counts (1)'
  recipes: 4
  outputs: 12
  set: '2026-11-11'
  run: full
```

| To | Do |
|---|---|
| change a limit | edit `max` / `min` / `abs_max` in `limits.yaml` and say why in `from`; run `score` |
| state a limit the brief gives | write it next to the check in `bench.yaml` (`max: 2.0`); it wins over `limits.yaml` |
| keep a check measured only | `limit: none` next to the check |
| check a limit against your eye | label outputs in the report: it shows how often the limit agreed with you and the value that would agree better. Nothing is applied; to accept one, change it as in the first row |
| have a limit set again from a run's results | delete its entry in `limits.yaml`; run `score --round full` |

**The limits hold for the inputs they were set on.** They are one number per check, taken across all
inputs, and many measurements depend on the input (how much light can move to the left half of a tall thin
vase is not what it is for a kettle). Limits frozen on five products rejected 94 of 100 good outputs on
fifteen other products; on a bench of very different recipes they came out too loose to fail anything. For
new inputs, start a new bench folder (its own `limits.yaml`) and read the measurements, not only the pass
counts. Setting limits per input is planned.

Not set: on a smoke round, on a run narrowed with `--inputs` or `--recipes`, for a check with fewer than
two recipes, and for a metric whose META has no `direction`. With one draw per recipe the margin is the
metric's `tolerance` alone. A limit set this way says "not clearly worse than the typical recipe in the
first run": if every recipe is poor, the typical one still passes.

## Masks as model inputs

A recipe can send a mask to models that take one (`$mask` in `params`):

```yaml
params: { inputs: { seedImage: $input, maskImage: $mask } }
mask: { edit: logo, polarity: white_is_edit }       # or edit: not(logo); white_is_keep
```

The runner draws the mask at the input's exact size from the named region and uploads it. Check
each model's mask convention in its schema and set `polarity` to match.

Known limit (Ideogram 4.5 Precise Edit, tested): a small *keep* island inside a mostly white mask is
not kept; the model regenerates it. A small *edit* area inside a black mask works pixel-exactly.
Masks are reliable for "change only this", not for "change everything except this".

## Router recipes: `model: auto`

A recipe with `model: auto` sends the request to Runware's Model Router, which picks the model. It is
scored like any other recipe, and the report gets a "Model Router" section: what was picked on each
call, how those outputs did against the checks, and how the same model did when called by name.

```yaml
# recipes/router-auto.yaml
id: router-auto
model: auto
routing:                      # optional; sent as the request's `routing` object
  allowedModels: bench        # shorthand: every model the bench's other recipes name (or a list of 2+)
  preferences: { quality: 5, speed: 0, cost: 0 }   # 0-5 each; leave out for even weights
  maxPrice: 0.10              # USD per request; also used as this recipe's `price` for the budget cap
  requirements: "with audio, 1080p or better"       # plain language, what no parameter can say
params:
  positivePrompt: ...
  inputs: { referenceImages: [$input] }
price: 0.08                   # needed when there is no maxPrice: the dearest model it could pick
```

- **Send only what every candidate accepts.** A value a model cannot take rules that model out, so a
  size, a seed or a model setting narrows the pool. What is left out is filled in by the router (seen:
  a square output from a portrait input, and two resolutions for the same request).
- **One request shape.** A model that wants the product in another field (`seedImage` instead of
  `referenceImages`) cannot be chosen by this recipe. Say so in `notes`.
- **Each draw is one call**, and the router may pick a different model each time. Leave `$seed` out:
  a seed rules out every candidate without a seed field. Results are cached per draw like any other recipe.
- **No `then` or `post` steps** on a router recipe yet.
- `excludedModels` (a list) is the opposite of `allowedModels`; the two cannot be combined.

## Task types: tools and text

A recipe's `taskType` says what kind of task it is (default `imageInference`). Besides images, video
(`videoInference`) and 3D (`3dInference`), the runner runs and scores these six. Each is one of the task
types Runware's Model Router accepts, so a `model: auto` recipe works for them too.

| `taskType` | The recipe sends | The output | What the checks compare |
|---|---|---|---|
| `upscale` | `inputs: { image: $input }`, `upscaleFactor` | a larger picture | the picture, at the input's size and at its own |
| `removeBackground` | `inputs: { image: $input }`, `outputFormat: PNG` | a picture with transparency | its alpha, with a reference outline of the subject |
| `imageMasking` | `inputs: { image: $input }` | a black and white mask | the mask, with a reference outline |
| `vectorize` | `inputs: { image: $input }` | an SVG | the SVG rendered at the input's width, and the file itself |
| `caption` | `inputs: { image: $input }`, `prompt` | text | the text (and, for judges, the input picture) |
| `textInference` | `messages: [{ role: user, content: $input }]`, `settings` | text | the text (and, for judges, the input text) |

```yaml
# recipes/bria-rmbg-2.yaml
id: bria-rmbg-2
taskType: removeBackground
model: bria:2@1
params: { inputs: { image: $input }, outputFormat: PNG }
price: 0.018
```

- **Reference outline.** A background remover or a masking model is judged against an outline you
  trust: `regions: { product: masks/item.png }` on the input, white = the subject. Draw or correct it
  by hand for the inputs that matter. `auto:<AIR>` makes one with a model, which then agrees with
  itself: do not use a model under test.
- **Text inputs.** An input whose file ends in `.txt` or `.md` is a text input: it is not uploaded,
  and `$input` is its content. Use it for `textInference` benches (one prompt or document per file).
- **Per-input facts for text checks**, next to `path`: `reference:` (a text the answer should be close
  to), `terms:` (words that must appear), `banned:` (words that must not). The same keys on a check
  apply to every input.
- **Draws.** Each draw is one more call of the same request, cached on its own, which shows how much
  the answer varies: useful for text, wasteful for a tool that always answers the same (the report says
  when every draw came back identical). Use `draws: 1` unless the variation is what you want to see.
- **Prices.** Text models are priced per token, so the listed price says little about one answer: give
  `price` (USD per output) from a smoke round. Add `includeUsage: true` to a `textInference` recipe to
  get token counts (`text_output_tokens`).
- **Ground truth for upscalers**, next to `path`: `original:` (the full-size picture this input was shrunk
  from). `upscale_truth_ssim` and `upscale_truth_psnr` compare the result with it.
- **One field of a JSON answer**: `field: title` on a text check reads that field instead of the whole
  answer (`{ id: text_words, field: title, max: 8 }`).
- **Reference outlines from a model**: `auto:<AIR>` uses the background remover you name
  (`auto:bria:2@1`); plain `auto:` uses BiRefNet General.
- **No product outline is bought** for cut-outs and masks (they are their own outline), vector files or
  text. Upscaled pictures get one like any picture.

The checks for each are in `metrics.md` (sections "Upscaled pictures", "Cut-outs and masks", "Vector
files", "Text").

## Your own model on Runware Serverless

A recipe can call an endpoint of a Runware Serverless app, so a model you trained or deployed yourself is
benchmarked next to the catalogue's models, with the same checks.

```yaml
id: klein4b-relight-lora
taskType: serverlessEndpoint
model: serverless:my-app            # a label for the report; nothing is looked up
serverless:
  app: my-app                       # the app id (`runware serverless apps list`)
  endpoint: sample                  # the endpoint path (`runware serverless apps endpoints my-app`)
  imageKey: image                   # field of the handler's answer with the picture as base64 (default: image)
  secondsKey: seconds               # field with the GPU seconds the handler measured (default: seconds)
  gpuPricePerSecond: 0.00044444     # USD, from `runware serverless gpus`
params:                             # the endpoint's payload, as the handler's parameters
  image: $input.base64              # the input file itself, base64 (an app has no use for Runware media URLs)
  prompt: "..."
  seed: $seed
price: 0.0015                       # USD per output, for the estimate
```

- **Cost** is the handler's GPU seconds times the GPU's rate: what one output used. Serverless bills GPU
  time per worker, so a cold start and the idle time before the worker scales down are billed too and are
  not in that figure. Say so in the recipe's `notes`.
- **Seeds:** an endpoint usually needs a seed, so `seed: $seed` (the draw's number) is the normal case
  here. The draws differ from each other and repeat on a re-run.
- **Not checked:** an app has no published schema, so `estimate` lists the recipe under "Parameters not
  checked". A wrong field is refused by the app (422), not run silently.
- The task's id is the Serverless task id, so a retry cannot run a call twice. A worker that scaled to
  zero takes minutes to come back; the runner waits (up to 30 minutes per call).

Writing, training or deploying the app is outside this skill: it benchmarks an endpoint that exists.

## Multi-step recipes

A recipe can continue after its first image:

```yaml
then:                       # a second task on the first output
  model: ideogram:4.5@precise-edit
  params: { inputs: { seedImage: $prev, maskImage: $mask, referenceImages: [$input] }, ... }
post:                       # local steps, no API cost
  - { transferDetail: logo, sigmaPx: 6, featherPx: 6 }      # new light, original fine detail
  - { restore: logo, featherPx: 4 }                          # paste the original pixels back
```

`$prev` is the previous step's image; for a `then` step, `$mask` is redrawn at that image's size.
If a plain recipe with the same first request exists, its image is reused as the first step, so
the only difference between the two recipes is what comes after (fair comparisons, no double cost).

Tested on a relight with a logo: `transferDetail` brought the lettering back with the new light;
`restore` was exact but visibly pasted; a masked `then` pass changed almost nothing. Pixel checks
favour whichever method copies pixels, so judge these with the vision panel and your own eye.

## Metrics: library plus your own

A metric id in `evaluate` resolves to a file: first the bench's `metrics/` folder (or the folders in
`metricDirs`, in order), then the runner's library. A bench file with a library id overrides it.
Every score records the
metric's fingerprint (a hash of its file), so a changed metric is visible in the results.

## Other optional fields

- `label:` on any metric gives it a readable column name in the report.
- `title:` (top level) is the report's heading.
- `judges:` (top level) is the vision-model panel; metrics use it via `judges: $judges`.
- `refs: [<media name>]` on a `vlm_*` metric shows those references to the judges.
- `report: { x: cost, y: "Colour" }` picks the trade-off chart's axes, by metric label or `cost`.
  Default: cost against the first colour check.
- Avoid YAML 1.1 surprises: keys like `on:`, `off:`, `yes:` are read as booleans by many parsers.
  The runner corrects them, but other tools may not.

## Example

A whole bench: `bench.yaml`, one recipe file and one metric written for it. The numeric checks carry
no limit: the first full run sets them (`limits.yaml`). The yes/no question needs none.

```yaml
# bench.yaml
title: "Which model adds a contact shadow without touching the product?"
task: "Add a soft contact shadow under the product."
goal: >
  Add a soft contact shadow under the product. The product and the backdrop colour must not change,
  and the label must stay readable.

inputs:
  - { path: inputs/sneaker_side.png, regions: { product: "auto:" } }                    # outline made on Runware
  - { path: inputs/boot_front.png,   regions: { product: masks/boot_front.png }, text: "NORTH TRAIL" }

requirements:
  - { need: "A soft shadow appears under the product",   checks: ["Contact shadow", "Shadow looks real (judges)"] }
  - { need: "The product does not move or change size",  checks: ["Aspect", "Shift (px)", "Outline"] }
  - { need: "The product keeps its colours",             checks: ["Product colour"] }
  - { need: "The backdrop keeps its colour",             checks: ["Backdrop hue"] }
  - { need: "The label stays readable",                  checks: ["Label text"] }
  - { need: "No text is added",                          checks: ["Extra text"] }

evaluate:
  pixel_shift:
    metrics:
      - { id: size_aspect, label: "Aspect" }
      - { id: phase_correlation, label: "Shift (px)" }
      - { id: mask_iou, region: product, label: "Outline" }
  deviation:
    metrics:
      - { id: deltaE2000_region, region: product, label: "Product colour" }
      - { id: deltaE2000_region, region: not(product), ignore_lightness: true, label: "Backdrop hue" }
  text_brand:
    metrics:
      - { id: ocr_cer, region: product, label: "Label text" }
      - { id: ocr_extra_text, label: "Extra text" }
  prompt_adherence:
    metrics:
      - { id: contact_shadow, label: "Contact shadow" }          # metrics/contact_shadow.py, written for this bench
      - id: vlm_checklist
        judges: $judges
        label: "Shadow looks real (judges)"
        questions:
          - "Is there a soft shadow directly under the product in image 2?"

judges: [google-gemini-3-1-flash-lite, anthropic-claude-haiku-4-5, openai-gpt-5-4-nano]
maxModels: 3
budget: { maxSpend: 5.00 }
draws: 3
recipes: all                   # every file in recipes/
```

```yaml
# recipes/ideogram-precise-shadow.yaml
id: ideogram-precise-shadow
model: ideogram:4.5@precise-edit
params:
  inputs: { seedImage: $input, maskImage: $mask }
  positivePrompt: >-
    Add a soft, short contact shadow directly under the product. Change nothing else.
  settings: { quality: high }
mask: { edit: not(product), polarity: white_is_edit }   # this model edits where the mask is white
price: 0.06
notes: >-
  maskImage: white = edit, black = keep, at the input's exact size. No seed is sent.
```

```python
# metrics/contact_shadow.py
"""How far the lightness drop under the product is from a soft shadow (0 = inside the wanted range)."""
from runware_eval.metric_api import *  # noqa: F401,F403

META = {"id": "contact_shadow", "family": "lighting", "trust": "deterministic", "kind": "change",
        "needs": ["reference", "region"], "unit": "L* outside 8 to 30", "direction": "lower", "tolerance": 1.0,
        "description": "Lightness drop in a band under the product against the input: 0 when it is a soft shadow (8 to 30 L*)."}


def compute(p, opt):
    ys, xs = np.nonzero(p.region("product"))
    band = np.zeros((p.H, p.W), bool)
    band[ys.max():ys.max() + max(4, p.H // 40), xs.min():xs.max()] = True
    band &= ~p.region("product")
    drop = float(np.median(p.lab_in[..., 0][band]) - np.median(p.lab_out[..., 0][band]))
    return {"value": max(8 - drop, drop - 30, 0.0), "drop": drop}
```

The model ids are examples. Confirm status, price and field names with `runware model pricing <air>` and
`runware model schema <air>` before writing a recipe.
