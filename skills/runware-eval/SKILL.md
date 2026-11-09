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

## Step 0 — Preflight: Runware MCP and Runware CLI, before anything else

The bench needs both, every time. Check them before any other step, including the existing-bench
question, and do not continue until both are ready. Do not substitute guessed REST calls, web
searches, or model knowledge from memory.

- **Runware MCP**: catalog discovery, schemas, pricing and the smoke round.
- **Runware CLI**: uploads local files at full size (the hosted MCP runs on Runware's servers and
  cannot read them), and gives the runner its login (the MCP's browser sign-in does not extend to
  scripts).

### 1. Check both (read-only)

| | Ready when | Otherwise |
|---|---|---|
| MCP | Tools such as `list_models`, `model_schema`, `run` exist in this session (e.g. `mcp__runware__list_models`) | `claude mcp list` shows `runware`: added, not connected or signed in. Not listed: missing. |
| CLI | `runware auth status` prints a table whose `Status` row is `valid` | Command not found: missing. Any other `Status` value (e.g. `not configured`): installed, not signed in. |

Read-only looks at the working folder (e.g. for an existing `bench.yaml`) are fine during this step.
Show the user this status in two lines, then fix what is missing.

### 2. Install what is missing, yourself (the user approves each command)

Install the CLI first: it needs no restart. Then the MCP.

- **CLI**
  - Windows with scoop: `scoop bucket add runware https://github.com/Runware/scoop-bucket.git` then
    `scoop install runware`. Without scoop, ask whether to install scoop first.
  - macOS: `brew install --cask runware/tap/runware`
  - Linux: `curl -fsSL https://cli.runware.ai/install.sh | sh`
  - If `runware` is still not found, call it by its full path (e.g. `~/scoop/shims/runware`).
- **MCP** (Claude Code): `claude mcp add --transport http runware https://mcp.runware.ai`. Skip the
  add if `claude mcp list` already shows it. Other clients, or no shell: give the user the URL
  `https://mcp.runware.ai` and where it goes in that client's MCP settings.

### 3. One message with everything only the user can do, in this order

Include only the steps that apply:

1. **CLI sign-in:** in a **separate terminal**, run `runware auth login` and paste the API key at the
   prompt (runware.ai → dashboard → API keys). Never ask for the key in the chat; never use `--key`.
2. **Reload for the MCP** (only if you added it in this session; `/mcp` will not list it yet):
   `/exit`, then `claude -c` in the same folder. It reopens this conversation.
3. **MCP sign-in:** `/mcp` → **runware** → **Authenticate**, and sign in in the browser.
4. Say "continue".

While they do this, ask one thing, so the wait is not wasted: if the folder already has a bench, the
existing-bench question below; otherwise Step 1 question 1 (goal and inputs). Nothing else.

### 4. Re-check both

When they say continue, run the checks in part 1 again. Proceed only when both are ready.

Urgency ("I'm in a hurry", "just get going") is not declining. Only if the user explicitly declines
the MCP: read the public catalog at `https://runware.ai/docs/models/index.json` and each model's
`schema` URL, and say the bench is in read-only mode. Only if they decline the CLI: use public URLs
they already host, or inline base64 through the MCP for a single small image (it fills the
conversation and forces downscaling). Never ask for a `.env` file.

Upload local inputs with `runware media upload <file> -F json` and use the returned `mediaUUID` in
MCP calls and in `bench.yaml`.

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
4. **Budget cap** in USD for one full run. Default plan: 1 seed in the smoke round, 2 seeds in the
   full run if the budget allows (they measure consistency). Say which you chose.

## Step 2 — Pick metrics

Load `references/metrics.md` and select per dimension:

1. Drop metrics whose `needs` the user cannot supply, and tell them which dimension lost coverage.
2. Prefer trust order: deterministic > learned > judge > human.
3. Add one cross-check from a different `family` for every dimension, so disagreement is visible.
4. Measure pixel shift before deviation (misalignment inflates ΔE).
5. Aesthetics or any judge metric: plan a calibration step (user labels 5–10 outputs good/bad).
   If agreement is low, fall back to blind pairwise ranking by the user.
6. No single weighted score. Gates disqualify; ranks order the survivors, shown against cost.

Show the chosen metrics, with one line on why each, and get a yes before continuing.

## Step 3 — Find candidates through the MCP

These are free, read-only calls: you may start them as soon as the dimensions are confirmed, in
parallel with metric sign-off. Propose recipes only after sign-off.

1. `list_capabilities`, then `list_models` filtered by the capability the goal needs
   (e.g. `edit`, `image-to-image`). Keep `live` models only.
2. `model_schema` for each. Read `x-modes` to keep only models that accept the inputs the goal needs
   (e.g. `seedImage + maskImage`). **Read field descriptions**, not just names: preservation
   behaviour, quality tiers and mask conventions live in prose.
3. `model_pricing` for each, and for every price tier.
4. Propose 6–10 **recipes**, not just models: include quality tiers, prompt variants and mask
   variants of strong candidates. A cheap tier of a good model is a real contender.

## Step 4 — Normalise and write the bench

Map each recipe's parameters from its own schema. Record every convention you had to translate in a
`notes` field. The ones that silently break benches:

- **Mask polarity** (edit tasks): some models use white = edit, others white = keep.
- **Reference inputs** (identity, style, product): field names, how many references, and the
  strength or weight scale differ per model. Do not assume one model's scale carries over.
- **Size and aspect**: allowed dimensions differ; note any model that snaps or pads.

Write `bench.yaml` following `references/bench-format.md`. The file is the deliverable: it must be
re-runnable later without an agent, and adding a new model must mean adding one recipe.

## Step 5 — Cost, smoke round, full run, report

The runner does the paid work. Install it once from this repo: `pip install --no-deps -e runner`
(add the listed dependencies if missing). Always call it as `python -m runware_eval …`: it works
without admin rights, whereas the `runware-eval` shortcut needs write access to Python's `Scripts`
folder, which system-wide installs often deny. If pip prints "Failed to write executable", the package
is still installed; only the shortcut is missing. It signs in with the CLI login.
Every command takes `--out <folder>`; results there are cached, so nothing is ever paid for twice.

1. **Estimate:** `python -m runware_eval estimate bench.yaml --round smoke`. Costs are *measured* averages from
   earlier runs in that folder, otherwise the highest *listed* price in the model's schema. Runware has
   no reliable dry-run (the `X-Runware-Dry-Run` header executed and billed in testing), so never
   promise a free price check. Show the user the table and get a yes.
2. **Smoke round:** `python -m runware_eval run bench.yaml --round smoke` (first input, first seed, every
   recipe). It records real cost and latency per task, masks every output and writes the report.
   Look at every output for inverted masks, cropping and ignored instructions; fix recipes first.
3. **Full run:** `python -m runware_eval estimate bench.yaml --round full` (now with measured costs), then, with
   the user's OK, `python -m runware_eval run bench.yaml --round full`. It stops before starting if the projected
   total would pass `budget.max_usd`.
4. **Report:** `python -m runware_eval report bench.yaml --round full --notes notes.json` rebuilds `report.html`:
   verdict, trade-off chart, check-by-check table, before/after slider with a colour-drift heatmap,
   region crops, gallery and all data, in one file. Put your reading of the results (what passed, what
   is misleading, what to change next) in `notes.json` as `findings` and `caveats`. Hand the user the
   report, not loose images.

Metrics marked `planned` in the registry (vision-model judges, OCR, human ranking) show as *not run*
in the report. Say so; never present them as passed.

**Before reporting, check the gates against the outputs.** A gate that every recipe fails, or one that
passes something visibly wrong (e.g. a hue-only backdrop check passing a black backdrop), is
mis-specified: fix or demote it, and say so in the caveats.

## Red flags — stop and correct

| Thought | Reality |
|---|---|
| "I already know the right metrics for this" | Ask first. Another user with the same inputs may care about different things. |
| "No model can preserve pixels, so I'll build a workaround" | Read the schemas first. Some models restore unchanged pixels by design. |
| "I'll search the community catalog for edit models" | `model_search` is community fine-tunes. Use `list_models` by capability. |
| "I'll write custom scripts for this user" | Write `bench.yaml`. A one-off script is not a bench. |
| "I'll loop `run` over the whole grid in chat" | The MCP is for setup and the smoke round. The runner executes. |
| "I'll dry-run it to get a free price" | Dry-run is unreliable on Runware. Estimate from measured smoke costs, and say which numbers are listed. |
| "The MCP isn't here; I'll call the API directly" | Install it (Step 0). The API without the MCP means guessing schemas. |
| "Inputs are URLs / already uploaded, so I can skip one of the two" | Step 0 needs both every time: the runner uses the CLI login. |
| "I'll just print the install command for the user" | If you can run it, run it. Leave the user only the sign-in and the reconnect. |
| "I'll ask for the key so I can run `runware auth login --key`" | Never. The user signs in at the CLI prompt in their own terminal. |
| "There's already a bench for this; I'll pick up where it left off" | Mention it and ask. A new request is a new bench unless the user says otherwise. |
| "Local files: I'll base64 them into the MCP call" | Install the CLI and upload at full size. Inline is a last resort for one small image. |

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
