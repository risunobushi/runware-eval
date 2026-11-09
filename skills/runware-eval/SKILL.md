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

## Step 0 — Preflight: the Runware MCP is required

Before anything else, check whether Runware MCP tools are available in this session (tools named
`list_models`, `model_schema`, `model_pricing`, `run`, e.g. `mcp__runware__list_models`).

**If they are missing, install it for the user. Do not continue without it**, and do not substitute
guessed REST calls, web searches, or model knowledge from memory.

- **You can run shell commands and the client is Claude Code:** say you are adding the hosted
  Runware MCP to their config, then run it yourself (the user approves the command):
  `claude mcp add --transport http runware https://mcp.runware.ai`
  If `claude mcp list` already shows `runware` but its tools are missing, it is added but not yet
  connected or signed in: skip the add.
- **Other clients** (Cursor, Claude Desktop, Codex), or no shell: give the user the server URL
  `https://mcp.runware.ai` and where to add it in that client's MCP settings.
- **Local server instead** (no browser sign-in): `claude mcp add runware -e RUNWARE_API_KEY=<key> --
  npx -y @runware/mcp`. The user runs this in their own terminal, so the key never enters the chat.

Then give the user the steps only they can do. A server added during a session is not loaded until
Claude Code restarts (`/mcp` will not list it yet), so the restart must keep the conversation:

1. Exit Claude Code (`/exit`).
2. Run `claude -c` in the same folder. It reopens this conversation with the new server loaded.
3. Run `/mcp`, select **runware**, choose **Authenticate**, and sign in in the browser.
4. Say "continue".

If the server was already configured before this session started, skip steps 1–2. Never ask for the
API key in the chat. While they install it,
you may ask Step 1 question 1 (goal and inputs) so the restart is not wasted. Nothing past that.

Urgency ("I'm in a hurry", "just get going") is not declining. Only if the user explicitly declines
the MCP: read the public catalog at
`https://runware.ai/docs/models/index.json` and each model's `schema` URL, and say that the bench
is being set up in read-only mode.

### Local input files

The hosted MCP runs on Runware's servers, so it cannot read local files, and its browser sign-in
does not extend to scripts or the runner. Getting local inputs to Runware, in order of preference:

1. **Runware CLI** (no key in chat or in project files). The user runs this in their own terminal:
   install it (`scoop install runware` after `scoop bucket add runware
   https://github.com/Runware/scoop-bucket.git` on Windows, `brew install --cask runware/tap/runware`
   on macOS, `curl -fsSL https://cli.runware.ai/install.sh | sh` on Linux), then `runware auth login`.
   You then upload with `runware media upload <file> -F json` and use the returned `mediaUUID` in
   MCP calls and in `bench.yaml`. The runner reuses the CLI login.
2. **Public URLs** the user already hosts.
3. **Inline base64 through the MCP**: only for one small image in a pinch. It fills the
   conversation and forces downscaling.

Do not ask the user to create a `.env` file while the CLI route is available.

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

## Step 5 — Cost, smoke round, hand-off

1. Estimate cost: inputs × recipes × seeds × price. If the runner is installed, use
   `runware-eval estimate bench.yaml` (it sends `X-Runware-Dry-Run: 1`, which prices a request without
   running it). Otherwise say the figure comes from listed prices. Never exceed the cap.
2. With the user's OK, run a **smoke round**: one input × every recipe via the MCP `run` tool. Look at
   every output for inverted masks, cropping and ignored instructions, and fix the recipes before
   spending more.
3. **Record cost and latency for every task** (`includeCost: true`, plus wall time). They are always
   measured; if they are missing, say so in the report rather than substituting listed prices silently.
4. **Finish with the HTML report, not loose images.** After scoring, run
   `python runner/report.py <bench_dir> <input> <outputs_dir> --notes <notes.json>`. It writes one
   self-contained page: verdict, the trade-off chart, gate-by-gate table, before/after slider, colour
   heatmap, logo crops and the full data. Put your reading of the results (what passed, what is
   misleading, what to change in round 2) in `notes.json` as `findings` and `caveats`.
5. Full run and scoring: `runware-eval run bench.yaml`. If the runner is not installed, stop after the
   smoke round and its report, and tell the user the bench is ready and what remains.

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
| "List price × N is close enough" | Use the dry-run estimate when available, and say which one you used. |
| "The MCP isn't here; I'll call the API directly" | Install it (Step 0). The API without the MCP means guessing schemas. |
| "I'll just print the install command for the user" | If you can run it, run it. Leave the user only the sign-in and the reconnect. |

## Quality bar

- The user chose the dimensions; every metric traces back to one of them.
- Every recipe's capabilities were verified in its schema, not assumed.
- Mask and other conventions are recorded per recipe.
- Cost was estimated and approved before any paid call.
- `bench.yaml` re-runs without an agent.

## Related skills

`runware-models` (catalog lookup), `runware-run` (execution contract and dry-run), `edit-image`,
`product-photography`, `character-consistency`, `text-in-image` (the outcomes this bench evaluates),
and the `migrate` skills (use a bench to prove a migrated recipe did not regress).
