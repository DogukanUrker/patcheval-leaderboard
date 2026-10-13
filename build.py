#!/usr/bin/env python3
"""Build data.js for the PatchEval leaderboard from BenchKit results.

usage: python3 build.py [path/to/BenchKit/results]

Each entry in ENTRIES names the run folder(s) it comes from. Several folders
are merged task by task: a later run fills in tasks that were missing or hit a
harness error in an earlier one (split or resumed runs). Prompts, responses
and traces are never copied into the site, only outcomes and counts.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "repos/BenchKit/results")
OUT = Path(__file__).parent / "data.js"
RELEASE = "pilot-20"

# where: "local" (run on the RTX 3060) or "api" (the model maker's official endpoint)
# gb: gguf file size, None when unknown. note: shown in the row details.
ENTRIES = [
    dict(name="Qwen3.8-Flash", quant="official Qwen API", where="api", gb=None, color="charcoal",
         runs=["2026-08-27_06-01-39"]),
    dict(name="Qwen3.8-27B", quant="GSQ-RCO IQ2_XS", where="local", gb=8.42, color="purple",
         runs=["2026-09-01_06-24-23"]),
    dict(name="Qwen3.8-27B", quant="official Qwen API", where="api", gb=None, color="slate",
         runs=["2026-08-27_18-39-41"]),
    dict(name="Qwen3.6-35B-A3B", quant="UD-Q4_K_XL", where="local", gb=22.85, color="blue",
         runs=["2026-08-25_20-38-01"]),
    dict(name="Tiel-Coder-35B-A3B", quant="UD-IQ4_XS", where="local", gb=17.73, color="pink",
         runs=["2026-09-29_21-47-22"]),
    dict(name="Ornith-1.5-35B", quant="Q4_K_M", where="local", gb=21.71, color="brown",
         runs=["2026-08-24_04-18-10", "2026-08-24_12-59-36"],
         note="first run hit 3 harness errors; those tasks were re-run in a resume slice and merged."),
    dict(name="Bonsai-2-27B", quant="Ternary PQ2_0", where="local", gb=7.21, color="green",
         runs=["2026-09-19_12-21-30"]),
    dict(name="MiniCPM-V-4.7-35B-A3B", quant="official MiniCPM API", where="api", gb=None, color="navy",
         runs=["2026-10-11_20-21-31"]),
    dict(name="Ornith-1.5-9B", quant="Q5_K", where="local", gb=None, color="teal",
         runs=["2026-08-25_00-09-24"]),
    dict(name="Saluki-27B", quant="Underdog 1.0 · IQ2 mix", where="local", gb=7.9, color="lime",
         runs=["2026-10-10_10-38-33"], note="Qwen3.8-27B finetune by ConwayResearch. sampling from its model card (temp 0.6)."),
    dict(name="Qwen3.8-27B", quant="ByteShape IQ2_XXS", where="local", gb=8.8, color="orange",
         runs=["2026-09-16_08-29-18"]),
    dict(name="Qwen3.8-35B-A3B", quant="Q4_K_M (distill)", where="local", gb=None, color="grape",
         runs=["2026-09-17_07-06-09"]),
    dict(name="Qwen3.8-27B", quant="AtomicChat AD-IQ2_XXS", where="local", gb=9.0, color="indigo",
         runs=["2026-08-26_08-13-22"]),
    dict(name="Spark-X2.5-4B", quant="8-bit", where="local", gb=None, color="gold",
         runs=["2026-09-11_18-40-08"]),
    dict(name="LFM2.5-8B-A1B", quant="Q4_K_M", where="local", gb=None, color="cyan",
         runs=["2026-08-26_20-44-01"], note="ran with 6 tasks in parallel; every other local run used 1."),
]


def outcome(t):
    if t.get("harness_error"):
        return "error"
    if t.get("passed"):
        return "repair" if t.get("repaired") else "pass"
    if t.get("loop_killed"):
        return "loop"
    if t.get("timed_out"):
        return "timeout"
    return "fail"


def load(run):
    data = json.loads((RESULTS / run / "results.json").read_text())
    rows = [r for r in data if "patcheval" in str(r.get("benchmark", "")).lower()]
    if len(rows) != 1:
        sys.exit(f"{run}: expected one patcheval row, found {len(rows)}")
    return rows[0]


def build(entry):
    tasks, meta = {}, []
    for run in entry["runs"]:
        row = load(run)
        meta.append(row)
        for t in row["tasks"]:
            prev = tasks.get(t["task_id"])
            if prev is None or prev["o"] == "error":
                tasks[t["task_id"]] = {
                    "o": outcome(t),
                    "calls": t.get("tool_calls") or 0,
                    "turns": t.get("model_turns") or 0,
                    "secs": round(t.get("response_time_s") or 0),
                }
    outs = [t["o"] for t in tasks.values()]
    scored = sum(o != "error" for o in outs)
    passed = sum(o in ("pass", "repair") for o in outs)
    first = sum(o == "pass" for o in outs)
    loops = sum(o == "loop" for o in outs)
    main = meta[-1] if entry["where"] == "api" else meta[0]
    return {
        "name": entry["name"], "quant": entry["quant"], "where": entry["where"],
        "gb": entry["gb"], "color": entry["color"], "note": entry.get("note", ""),
        "scored": scored, "passed": passed, "first": first, "loops": loops,
        "errors": len(outs) - scored,
        "tok_s": round(main.get("tok_s") or 0, 1) if entry["where"] == "local" else None,
        "hours": round(sum(m.get("total_time") or 0 for m in meta) / 3600, 1),
        "tool_calls": sum(t["calls"] for t in tasks.values()),
        "date": entry["runs"][-1][:10],
        "runs": entry["runs"],
        "harness": f'{main.get("harness_label", "Pi agent")} {main.get("harness_version", "")}'.strip(),
        "tasks": tasks,
    }


def main():
    models = [build(e) for e in ENTRIES]
    order = list(dict.fromkeys(tid for m in models for tid in m["tasks"]))
    for m in models:
        if len(m["tasks"]) != 20:
            print(f"warning: {m['name']} {m['quant']} covers {len(m['tasks'])} tasks", file=sys.stderr)
    payload = {
        "release": RELEASE,
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "task_order": order,
        "models": models,
    }
    OUT.write_text("window.PATCHEVAL = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT} ({len(models)} models, {len(order)} tasks)")
    for m in models:
        print(f"  {m['passed']:>2}/{m['scored']:<2} first {m['first']:>2} loops {m['loops']}  {m['name']} · {m['quant']}")


if __name__ == "__main__":
    main()
