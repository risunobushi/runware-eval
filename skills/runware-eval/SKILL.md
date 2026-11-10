---
name: runware-eval
description: >
  Set up a reproducible test bench that compares Runware models and settings against the user's own
  goal and inputs. Use when the user says "which model is best for my use case", "compare these
  models", "benchmark", "A/B test models", "evaluate outputs", "did the product change", "measure
  drift / fidelity / pixel shift / aesthetics", "set up a testing bench", "re-test when new models
  ship", or "check my migrated pipeline didn't regress". Not for a one-off generation; for that use
  the outcome skill (edit-image, product-photography, ...).
---

# Runware eval

Turn "which model is best for this?" into a bench file that anyone can re-run: the user's inputs, a
set of recipes (model × settings × prompt × mask), and the metrics that measure *their* definition
of good. The agent's job is setup and judgement. Execution belongs to the runner, not to a chat loop.

**Core rule: the user decides what "good" means; the catalog decides what is possible.** Never pick
metrics before asking, and never claim what a model can or cannot do without reading its schema.

## Step 0 — Preflight: Runware CLI and uv, before anything else

The bench needs both, every time. Check them before any other step, including the existing-bench
question, and do not continue until both are ready. Do not substitute guessed REST calls, web
searches, or model knowledge from memory.

- **Runware CLI**: the catalog (search, schemas, pricing, examples), uploads of local files at full
  size, and the login the runner uses. One sign-in covers everything.
- **uv**: runs the bench runner in its own isolated environment, on a pinned Python 3.12 that uv
  downloads if needed. Nothing is installed into the user's Python (they need none), so no admin
  rights, PATH changes or dependency clashes.

No MCP server is needed: every catalog question goes through the CLI, and the runner does the paid
work. Both work in any agent with a shell, and nothing needs a restart.

### 1. Check both (read-only)

| | Ready when | Otherwise |
|---|---|---|
| CLI | `runware auth status` prints a table whose `Status` row is `valid` | Command not found: missing. Any other `Status` value (e.g. `not configured`): installed, not signed in. |
| uv | `uv --version`, or `~/.runware-eval/tools/uv --version`, prints a version | Neither found: missing. |

Read-only looks at the working folder (e.g. for an existing `bench.yaml`) are fine during this step.
Show the user this status in two lines, then fix what is missing.

### 2. Install what is missing, yourself (the user approves each command)

Neither needs a restart or admin rights.

- **CLI**
  - Windows with scoop: `scoop bucket add runware https://github.com/Runware/scoop-bucket.git` then
    `scoop install runware` (adding a bucket needs git: `scoop install git` first if it is missing).
    Without scoop, ask whether to install scoop first.
  - macOS: `brew install --cask runware/tap/runware`
  - Linux: `curl -fsSL https://cli.runware.ai/install.sh | sh`
- **uv**: install it self-contained in one folder, without changing PATH or adding an updater
  (deleting the folder removes it). The installers ask nothing.
  - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$HOME/.runware-eval/tools" sh`
  - Windows (PowerShell): `$env:UV_UNMANAGED_INSTALL="$HOME\.runware-eval\tools"; powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Then call it as `~/.runware-eval/tools/uv`. If the user already has uv (or prefers `scoop install uv` /
    `brew install uv`), use that instead.

If a freshly installed command is not found, call it by its full path (e.g. `~/scoop/shims/runware`)
rather than asking for a restart. If an install fails, show the user the error and stop there.

### 3. The one step only the user can do

If the CLI is not signed in: ask them to open a **separate terminal**, run `runware auth login` and
paste their API key at the prompt (runware.ai → dashboard → API keys), then say "continue". Never ask
for the key in the chat; never use `--key`.

While they do this, ask one thing, so the wait is not wasted: if the folder already has a bench, the
existing-bench question below; otherwise Step 1 question 1 (goal and inputs). Nothing else.

### 4. Re-check

When they say continue, run the checks in part 1 again. Proceed only when both are ready.

Urgency ("I'm in a hurry", "just get going") is not declining. Only if the user explicitly declines
the CLI: read the public catalog (`https://runware.ai/docs/models/index.json` and each model's
`schema` URL) and say the bench can be designed but not run until they sign in. Never ask for a
`.env` file.

The runner uploads local inputs itself (once, through the CLI) and records their URLs; nothing to do
by hand.

## Existing benches: mention, then ask

If you find a `bench.yaml` (or earlier outputs or reports) in the working folder, do not assume it is
what the user wants, and do not summarise its results or plan its next round. Say in one or two
lines that it exists (path, its goal in a few words, whether it has results), then ask:

- **Start a new bench** (default for a new request): leave the existing one untouched.
- **Re-run or extend the existing bench**: new inputs, recipes or seeds on the same goal.
- **Review the existing results** first.

In the same message you may ask which input files to use (and whether they are the ones already in
the bench). Then **wait for the answer before doing anything else**: no uploads, no further
intake. (Step 0 has already run: the tools are ready whichever option they choose.) Describe results only if they choose to review them.

## Step 1 — Intake: ask what to evaluate

Ask in this order and wait for answers. If the user has already answered part of a question, ask
only the rest. If they answer several at once in free text, map their words onto the table below,
**show the table with their choices marked**, and ask them to confirm. Never skip showing the table:
it is how users discover dimensions they had not thought of.

1. **The goal** in one sentence, and the inputs (files or URLs). How many, and how varied.
2. **What to evaluate** — present the dimensions as a multi-select. Do not pre-select:

   | Dimension | The question it answers |
   |---|---|
   | Deviation | Did it change what it should not? (colour, structure) |
   | Pixel shift | Did anything move, warp, crop or resize? |
   | Identity | Is it still the same face / product / character? |
   | Text & brand | Is the copy and logo exactly right? |
   | Prompt adherence | Did it do what the brief asked? |
   | Aesthetics | Is it good? (subjective — needs calibration) |
   | Technical quality | Is it clean? (sharpness, artefacts, banding) |

   Cost, latency and failure rate are always measured. Say so.
3. **Follow-ups only for the chosen dimensions**: which region must stay fixed (do they have masks,
   or should the bench generate them), expected text, reference identity, and for each dimension
   whether it is a **gate** (must pass) or a **rank** (order the survivors).
4. **Budget and size:** the budget cap in USD for one full run, and the **maximum number of models**
   to test (e.g. 3 or 5; it cuts time and spend). Write it as `max_models` in `bench.yaml` and
   propose exactly that many in Step 3; the runner refuses more. Seeds: 1 in the smoke round, **3 in
   the full run** (`seeds: [1, 2, 3]`), so one unlucky or lucky generation does not decide: each
   check is judged by `pass_rule` (default `majority` of seeds, per input; also `all` or `any`).

## Step 2 — Pick metrics

Metrics are files, like recipes: a curated library ships with the runner (listed in
`references/metric-catalog.md`, generated from the code), and a bench can add its own in `metrics/`
(or shared `metric_dirs`). `uv run --project <runner> runware-eval metrics list bench.yaml` shows
what this bench can use. Load `references/metrics.md` for how to choose, then select per dimension:

1. Drop metrics whose `needs` the user cannot supply, and tell them which dimension lost coverage.
2. Prefer trust order: deterministic > learned > judge > human.
3. Add one cross-check from a different `family` for every dimension, so disagreement is visible.
4. Measure pixel shift before deviation (misalignment inflates ΔE).
5. Aesthetics or any judge metric: plan the calibration step (Step 5) — the user labels outputs
   good or bad, blind; metrics that disagree with them are flagged, and the blind pairwise ranking
   becomes the ranking that counts.
6. No single weighted score. Gates disqualify; ranks order the survivors, shown against cost.

Show the chosen metrics, with one line on why each, and get a yes before continuing.

**When no metric fits**, write one: a file in the bench's `metrics/` folder with a `META` dict and a
`compute(pair, opt)` function, following the contract in the runner's `metric_api.py`. Set `kind`
honestly: `preserve` (an unchanged output must pass), `change` (the task asks for change, so an
unchanged output must fail) or `info`. Then:

1. Show the user the code and get a yes: metric files run on their machine.
2. Run `runware-eval metrics control bench.yaml`. It scores every input against an unchanged copy of
   itself; a control that goes the wrong way means the metric or its threshold is broken.
3. Never edit the runner's library to add a bench-specific metric.

Four worked examples of bench-specific metrics (written for a relighting bench) are in the repo's
`examples/metrics/`: copy one as a starting point.

## Step 3 — Find candidates in the catalog

These are free, read-only calls: you may start them as soon as the dimensions are confirmed, in
parallel with metric sign-off. Propose recipes only after sign-off. Add `-F json`, and keep stderr
out of what you parse (`2>/dev/null`): a `Showing N of M results` footer goes there.

1. **Search:** `runware model search --source official --capabilities <cap> --limit 100`. Tags are
   `io:<from>-to-<to>` (e.g. `io:image-to-video`, `io:image-to-3d`) and `op:<operation>` (e.g.
   `op:edit`, `op:inpaint`); repeat `--capabilities` to combine. If unsure of a tag, search without
   it and read the results' `capabilities`. The default limit is 20 and truncates silently.
2. **Status and price:** `runware model pricing <air> -F json` gives `status` (keep `live` only) and
   the model's slug (`model`). It only lists a few example configurations; the real rates per unit
   and tier are in the public schema, `info.x-pricing.rates`. Drop any model whose pricing or schema
   call fails, even if search lists it.
3. **Schema:** `runware model schema <air> -F json` (`requestSchema.properties`): input media under
   `inputs`, model options under `settings` and `providerSettings.<provider>`. Use only these fields,
   with their exact names, and **read their descriptions**: preservation behaviour, quality tiers and
   mask conventions live in prose. Accepted input combinations are `info.x-modes` in the public
   schema, `https://runware.ai/docs/models/<slug>/schema.json` (the slug, not the AIR; fetch with
   curl, as some clients are refused). `runware model examples <air> -F json` shows a real request
   when the shape is unclear.
4. **Defaults that change cost or results:** note them per recipe and set them deliberately. Seen so
   far: audio on by default (costs more), prompt rewriting on by default (`promptExtend`,
   `promptUpsampling`, `enhancePrompt`: hurts reproducibility), fixed duration steps or minimums, and
   quality or speed modes.
5. **Propose recipes, not just models:** quality tiers, prompt variants and mask variants of strong
   candidates; a cheap tier of a good model is a real contender. Size the list to the budget:
   recipes x inputs x seeds x price must fit the cap for the full run, not just the smoke round.

## Step 4 — Normalise and write the bench

Map each recipe's parameters from its own schema. Record every convention you had to translate in a
`notes` field. The ones that silently break benches:

- **Mask polarity** (edit tasks): some models use white = edit, others white = keep.
- **Reference inputs** (identity, style, product): field names, how many references, and the
  strength or weight scale differ per model. Do not assume one model's scale carries over.
- **Size and aspect**: allowed dimensions differ; note any model that snaps or pads.

Write each recipe as its own file in `recipes/<id>.yaml` (self-contained: prompts written out, notes
on every translated convention), and list them by id in `bench.yaml`, following
`references/bench-format.md`. Before creating a recipe, run
`uv run --project <runner> runware-eval recipes list bench.yaml`: if a recipe for the same model and
settings already exists in the bench's recipe folders (or a team folder in `recipe_dirs`), reuse it
instead of writing a near-duplicate. The bench is the deliverable: it must re-run later without an
agent, and adding a model must mean adding one recipe file.

## Step 5 — Cost, smoke round, full run, report

Commands that only read results (`score`, `report`, `label`, `calibrate`, `metrics control`) need no
Runware login: anyone with the run folder can re-score it and rebuild its report; vision judges then
use their cached answers. And the report itself is one HTML file anyone can open in a browser.

The runner does the paid work. Do not `pip install` it. Run it through uv, which builds an isolated
environment on first use (about a minute) and reuses it afterwards:

`uv run --project <runner> runware-eval …`

`<runner>` is the `runner/` folder of the runware-eval repo. Installed as a plugin, it sits next to
`skills/`: two levels above this skill's base directory, then `runner`. Otherwise look for a
`runware-eval/runner/pyproject.toml` in the working folder. If the repo is not on disk at all,
use `uvx --from "git+https://github.com/risunobushi/runware-eval#subdirectory=runner" runware-eval …`
instead. The runner signs in with the CLI login.
Every command takes `--out <folder>`; results there are cached, so nothing is ever paid for twice.

1. **Estimate:** `uv run --project <runner> runware-eval estimate bench.yaml --round smoke`. Costs are *measured* averages from
   earlier runs in that folder, otherwise the highest *listed* price in the model's schema. Runware has
   no reliable dry-run (the `X-Runware-Dry-Run` header executed and billed in testing), so never
   promise a free price check. Show the user the table and get a yes.
2. **Smoke round:** `uv run --project <runner> runware-eval run bench.yaml --round smoke` (first input, first seed, every
   recipe). It records real cost and latency per task, masks every output and writes the report.
   Look at every output for inverted masks, cropping and ignored instructions; fix recipes first.
3. **Full run:** `uv run --project <runner> runware-eval estimate bench.yaml --round full` (now with measured costs), then, with
   the user's OK, `uv run --project <runner> runware-eval run bench.yaml --round full`. It stops before starting if the projected
   total would pass `budget.max_usd`.
4. **Report:** `uv run --project <runner> runware-eval report bench.yaml --round full --notes notes.json` rebuilds `report.html`:
   the best recipe and what it still misses, trade-off chart, check-by-check table, before/after slider with a colour-drift heatmap,
   region crops, gallery and all data, in one file. Put your reading of the results (what passed, what
   is misleading, what to change next) in `notes.json` as `findings` and `caveats`. Hand the user the
   report, not loose images.

5. **Calibrate against the user's eye** (after the smoke round, and again after the full run):
   `uv run --project <runner> runware-eval label bench.yaml --round <r>` makes a blind labeling page
   (good or bad, and "which is better" on random pairs). The user labels what they can and downloads
   `labels.json`; `runware-eval calibrate bench.yaml --round <r> --labels <file>` reports how often
   each check agreed with them, the threshold that would agree best, which rank metrics order their
   good above their bad, and a human ranking (Bradley-Terry). Show the suggestions; change
   `bench.yaml` only with the user's yes. Below about 20 labels, call the suggestions hints.

Vision-model checks run in `score` as the second stage of a funnel: only outputs that fail at most
`judge_when.max_failed_checks` pixel checks are judged, with one combined call per judge (about
$0.006 per judged output; cached; `--no-judges` skips them). When picking metrics in Step 2, give the
judges only questions no pixel check can answer. 3D outputs (GLB) and video
outputs (MP4) need nothing extra: the runner renders or reads them into images first, see the 3D and
video sections of `references/metrics.md`. For video recipes set `taskType: videoInference`, pass the
start image in `inputs.frameImages`, switch audio and prompt rewriting off, and give `price_usd`
(video is priced per second). Metrics marked `planned` in the
registry (OCR) show as *not run* in the report. Say so; never present them as passed.

**Before reporting, check the gates against the outputs.** A gate that every recipe fails, or one that
passes something visibly wrong (e.g. a hue-only backdrop check passing a black backdrop), is
mis-specified: fix or demote it, and say so in the caveats.

## Red flags — stop and correct

| Thought | Reality |
|---|---|
| "I already know the right metrics for this" | Ask first. Another user with the same inputs may care about different things. |
| "No model can preserve pixels, so I'll build a workaround" | Read the schemas first. Some models restore unchanged pixels by design. |
| "I'll search the whole catalog for edit models" | Without `--source official` the search includes community fine-tunes. Filter by source and capability. |
| "I'll write custom scripts for this user" | Write `bench.yaml`. A one-off script is not a bench. |
| "I'll loop single API calls over the whole grid in chat" | The runner executes, with caching, budget and cost records. |
| "I'll dry-run it to get a free price" | Dry-run is unreliable on Runware. Estimate from measured smoke costs, and say which numbers are listed. |
| "I'll write the request from memory" | Read the model's schema with `runware model schema` first. Field names differ per model. |
| "Inputs are URLs / already uploaded, so I can skip one of the two" | Step 0 needs both every time: the runner uses the CLI login and runs through uv. |
| "I'll add this check to the runner's code" | Write it in the bench's `metrics/` folder, show it, run the controls. |
| "The numbers look plausible, so the checks work" | Run `metrics control` and look at the outputs. Plausible numbers hid three broken checks in testing. |
| "I'll put the recipes inline in bench.yaml" | One file per recipe in `recipes/`, so they can be shared and matched by fingerprint. |
| "I'll `pip install` the runner" | Never into the user's Python. Run it through uv. |
| "I'll just print the install command for the user" | If you can run it, run it. Leave the user only the sign-in. |
| "I'll ask for the key so I can run `runware auth login --key`" | Never. The user signs in at the CLI prompt in their own terminal. |
| "There's already a bench for this; I'll pick up where it left off" | Mention it and ask. A new request is a new bench unless the user says otherwise. |
| "I'll install the Runware MCP too" | Not needed: the CLI covers the catalog and the runner does the work. One sign-in, no restart. |

## Quality bar

- The user chose the dimensions; every metric traces back to one of them.
- Every recipe's capabilities were verified in its schema, not assumed.
- Mask and other conventions are recorded per recipe.
- Cost was estimated and approved before any paid call.
- `bench.yaml` re-runs without an agent.

## Related skills

`runware-models` (catalog lookup), `runware-run` (execution contract), `edit-image`,
`product-photography`, `character-consistency`, `text-in-image` (the outcomes this bench evaluates),
and the `migrate` skills (use a bench to prove a migrated recipe did not regress).
