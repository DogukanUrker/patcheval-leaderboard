# PatchEval leaderboard

Static site for [PatchEval](https://huggingface.co/datasets/DogukanUrker/PatchEval) results. Plain HTML, no build step on the server.

- `index.html`: the page (leaderboard, per-task matrix, method, run instructions)
- `data.js`: generated data, loaded by the page
- `build.py`: makes `data.js` from BenchKit `results/` folders

## Add a model

1. Add an entry to `ENTRIES` in `build.py` with its run folder(s).
2. `python3 build.py` (defaults to `~/repos/BenchKit/results`).
3. Check the printed scores, then deploy.

Several run folders in one entry are merged task by task, so a resumed or split run counts once. Only outcomes and counts go into `data.js`. Prompts, responses and traces never do.
