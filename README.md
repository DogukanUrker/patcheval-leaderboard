# PatchEval leaderboard

Static site for [PatchEval](https://huggingface.co/datasets/DogukanUrker/PatchEval) results. Plain HTML, no build step on the server.

- `index.html`: the page (leaderboard, per-task matrix, method, run instructions)
- `data.js`: generated data, loaded by the page
- `trace.js`: the trace viewer (click any task cell, or open `#t/<slug>/<task>`)
- `traces/<slug>/<task>.json.gz`: one public agent trace per model and task, loaded on demand
- `build.py`: makes `data.js` and `traces/` from BenchKit `results/` folders

## Add a model

1. Add an entry to `ENTRIES` in `build.py` with its run folder(s).
2. `python3 build.py` (defaults to `~/repos/BenchKit/results`).
3. Check the printed scores, then deploy.

Several run folders in one entry are merged task by task, so a resumed or split run counts once. Only outcomes and counts go into `data.js`.

## Dataset revisions

When a hidden test is fixed in a new PatchEval revision, past runs are regraded
instead of rerun. `rescores.json` maps each changed task to the new
fail-to-pass exit code of every run folder, measured by running the new hidden
test on that run's saved final patch in the task's validation image. The
regression result carries over, since that suite never includes the hidden
test. Only the final patch is saved, so a run that passes after a repair round
counts as "solved on repair". Runs that already record that `dataset_revision`
are skipped. The build stops if an older run has no rescore for a listed task.

- r2 (2026-10-27): `pygments-2816`. Bonsai-2-27B PTQ1_0 goes from 15 to 16.

## Traces

Each trace keeps what the agent saw and did: the issue, every tool call with its output, the reasoning, the repair prompt, the final patch, and the hidden test exit codes. It never keeps the hidden grader output (the fail-to-pass and regression logs), so the hidden tests stay hidden.

Before anything is written, `build.py` checks every trace for:

- hidden test names from `tasks.jsonl`. A name that already exists in the parent source is fine, and known false hits go in `LEAK_OK` with the reason.
- private strings: hub paths, tailnet IPs, API tokens.

Any hit stops the build. `vercel.json` and `robots.txt` keep `traces/` out of search results.
