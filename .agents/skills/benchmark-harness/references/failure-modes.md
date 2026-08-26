# Failure modes

Error → cause → fix. Read the last 40 lines of the run log before acting; never re-run a
30-minute suite blind.

## Preflight

| Message | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: benchkit` | package not installed in this interpreter | `pip install -e .` from the repo root |
| `./bench: No such file or directory` | wrong cwd | `cd` to the repo; set `BENCH_REPO` for next time |
| `validate` prints less than `16/16` | a broken oracle or reference solution | stop and fix the harness. **Never** edit a task, test or `check` to make it pass |
| `harness list` shows `not found on PATH` | harness binary not installed for this user | install it, or benchmark a different harness |

## Model selection

| Message | Cause | Fix |
|---|---|---|
| `no model selected for <h>; pass --model …` | ran without `-m` in a non-tty | always pass `-m`; the interactive picker cannot work in an agent shell |
| `no model matching 'x' in this setup` | spec not in that harness's catalogue | pick from the printed list, or from `bench harness models` |
| `'x' matches several models — say which` | substring hit more than one | give the full `provider/model` |
| `provider 'p' is not configured here` | `--provider` unknown to that harness | drop `--provider`; ids resolve globally |
| claude-code tasks all fail instantly | bad model id, taken literally (it cannot enumerate) | smoke-test `claude -p 'reply with OK' --model <spec>`; fall back to the bare alias |

## Run

| Message | Cause | Fix |
|---|---|---|
| `harness '<h>' is not usable here: …` | binary missing, no model, or endpoint unreachable | read the detail; it names which of the three |
| `harness runs need an agentic suite` | `core16` / `hard12` / `all` requested | use `agentic`, `agentic-hard` or `agentic-all`; ask the user, don't switch silently |
| `--endpoint needs --model <id served by that endpoint>` | endpoint given without a model | name the id the endpoint reports at `/v1/models` |
| endpoint `/v1/messages` unreachable (claude-code) | server serves OpenAI but not the Anthropic Messages API | claude-code cannot be pointed at it; use pi or opencode for that endpoint |
| tasks time out at the task timeout | slow model, or a loop with no progress | raise `--timeout`, or lower `--concurrency` if the endpoint is saturated |
| run dies with no output | harness crashed on launch | re-run the same command in the foreground once, without `nohup`, to see stderr |

## Results

| Symptom | Cause | Fix |
|---|---|---|
| `reasoning_tokens` is `0` on claude-code | Claude Code reports thinking tokens in a field this stack zeroes | not a bug; those tokens are inside `output_tokens`. Say so when reporting |
| scores differ from an isolated `bench harness run` | live mode includes your skills, MCP servers and plugins | expected — that difference is the measurement |
| a second run refuses to overwrite the report | `results/` is append-only | keep both; the runner already picks a unique path |
| two runs land in one file | same label, same day | pass `--label` to distinguish them |
