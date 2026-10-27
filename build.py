#!/usr/bin/env python3
"""Build data.js for the PatchEval leaderboard from BenchKit results.

usage: python3 build.py [path/to/BenchKit/results]

Each entry in ENTRIES names the run folder(s) it comes from. Several folders
are merged task by task: a later run fills in tasks that were missing or hit a
harness error in an earlier one (split or resumed runs).

data.js holds only outcomes and counts. Each (model, task) agent trace goes to
traces/<slug>/<task>.json.gz and is loaded only when someone opens it. The
hidden grader output (fail-to-pass and regression test logs) is never
exported, and every trace is checked for hidden test names and private
strings before it is written.
"""
import gzip
import json
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "repos/BenchKit/results")
OUT = Path(__file__).parent / "data.js"
TRACES = Path(__file__).parent / "traces"
DATASET = Path.home() / "datasets/PatchEval"
RELEASE = "pilot-20"
REVISION = 2
# Tasks whose hidden test changed in a later revision. Each past run is
# regraded by running the new hidden test on that run's saved final patch:
# run folder -> new fail-to-pass exit code. Regression results carry over,
# since the regression suite never includes the hidden test.
RESCORES = json.loads((Path(__file__).parent / "rescores.json").read_text())

# where: "local" (run on the RTX 3060) or "api" (the model maker's official endpoint)
# gb: gguf file size, None when unknown. note: shown in the row details.
ENTRIES = [
    dict(name="Raon-1-mini", quant="IQ4_XS (preview)", where="local", gb=16.1, color="rose",
         runs=["2026-10-25_15-43-15", "2026-10-25_23-46-52"],
         note="KRAFTON Raon-1 mini preview (30B-A4B) on KRAFTON's llama.cpp fork. run split in two: tasks 1-6, then a slice for 7-20."),
    dict(name="Flint-40B-A2.5B", quant="UD-Q3_K_XL (preview)", where="local", gb=18.49, color="amber",
         runs=["2026-10-23_12-31-16"], note="Recursive Flint, coding-agent MoE. llama.cpp PR #30928 runtime."),
    dict(name="Spark-X2.6-4B", quant="Q8_0", where="local", gb=4.38, color="olive",
         runs=["2026-10-24_07-59-05"]),
    dict(name="Nemotron-3.5-Bolt-74B-A9B", quant="UD-IQ1_S", where="local", gb=18.51, color="mint",
         runs=["2026-10-21_06-36-25"]),
    dict(name="LFM2.5-24B-A2B", quant="QAD-Q4_0", where="local", gb=13.58, color="sienna",
         runs=["2026-10-14_09-31-35"]),
    dict(name="Bonsai-2-9B", quant="Ternary PQ2_0", where="local", gb=2.42, color="plum",
         runs=["2026-10-17_13-21-58", "2026-10-17_14-56-59"],
         overrides={"structlog-710": "fail", "pygments-2816": "timeout"},
         note="sqlit-246 hit a real harness error (docker disk full) and was re-run and merged. structlog-710 and pygments-2816 were logged as harness errors, but the model deleted or broke the repo itself, so they count as failures."),
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
    dict(name="Bonsai-2-27B", quant="Ternary PTQ1_0", where="local", gb=6.4, color="green",
         runs=["2026-10-26_13-58-10"], note="6.4 GB file includes the MTP head. ran on a faster runtime than the PQ2_0 run, so tok/s is not comparable between the two."),
    dict(name="Bonsai-2-27B", quant="Ternary PQ2_0", where="local", gb=7.21, color="pine",
         runs=["2026-09-19_12-21-30"]),
    dict(name="MiniCPM-V-4.7-35B-A3B", quant="official MiniCPM API", where="api", gb=None, color="navy",
         runs=["2026-10-11_20-21-31"]),
    dict(name="Ornith-1.5-9B", quant="Q5_K_M", where="local", gb=6.64, color="teal",
         runs=["2026-08-25_00-09-24"]),
    dict(name="Saluki-27B", quant="Underdog 1.0 · IQ2 mix", where="local", gb=7.9, color="lime",
         runs=["2026-10-10_10-38-33"], note="Qwen3.8-27B finetune by ConwayResearch. sampling from its model card (temp 0.6)."),
    dict(name="Qwen3.8-27B", quant="ByteShape IQ2_XXS", where="local", gb=8.8, color="orange",
         runs=["2026-09-16_08-29-18"]),
    dict(name="Qwen3.8-35B-A3B", quant="Q4_K_M (distill)", where="local", gb=21.71, color="grape",
         runs=["2026-09-17_07-06-09"]),
    dict(name="Qwen3.8-27B", quant="AtomicChat AD-IQ2_XXS", where="local", gb=9.0, color="indigo",
         runs=["2026-08-26_08-13-22"]),
    dict(name="Spark-X2.5-4B", quant="Q8_0", where="local", gb=4.38, color="gold",
         runs=["2026-09-11_18-40-08"]),
    dict(name="LFM2.5-8B-A1B", quant="Q4_K_M", where="local", gb=5.16, color="cyan",
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


def slug(entry):
    return re.sub(r"[^a-z0-9]+", "-", f'{entry["name"]} {entry["quant"]}'.lower()).strip("-")


def build(entry):
    tasks, meta, raw, revisions = {}, [], {}, {}
    for run in entry["runs"]:
        row = load(run)
        meta.append(row)
        revisions[run] = row.get("dataset_revision") or 1
        for t in row["tasks"]:
            prev = tasks.get(t["task_id"])
            if prev is None or prev["o"] == "error":
                raw[t["task_id"]] = (run, t)
                tasks[t["task_id"]] = {
                    "o": outcome(t),
                    "calls": t.get("tool_calls") or 0,
                    "turns": t.get("model_turns") or 0,
                    "secs": round(t.get("response_time_s") or 0),
                }
    for tid, rescore in RESCORES.items():
        if tid not in raw or tasks[tid]["o"] == "error":
            continue
        run, t = raw[tid]
        if revisions[run] >= rescore["revision"]:
            continue  # graded with the fixed test already
        if run not in rescore["runs"]:
            sys.exit(f"{run}: {tid} has no rescore for revision {rescore['revision']}")
        ws = t.get("workspace") or {}
        if rescore["runs"][run] == 0 and ws.get("regression_exit_code") == 0:
            # only the final patch is saved, so a pass after a repair round
            # can't be credited as first try
            tasks[tid]["o"] = "repair" if t.get("repair_attempts_used") else "pass"
    for tid, o in entry.get("overrides", {}).items():
        tasks[tid]["o"] = o
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
        "tok_s": round(main.get("tok_s") or 0, 1) or None,
        "hours": round(sum(m.get("total_time") or 0 for m in meta) / 3600, 1),
        # agent time: summed time of the counted tasks. ties on the board are broken by it.
        # unlike run wall time it does not double count re-run tasks or shrink with parallel tasks.
        "agent_s": sum(t["secs"] for t in tasks.values()),
        "tool_calls": sum(t["calls"] for t in tasks.values()),
        "date": entry["runs"][-1][:10],
        "runs": entry["runs"],
        "harness": f'{main.get("harness_label", "Pi agent")} {main.get("harness_version", "")}'.strip(),
        "slug": slug(entry),
        "tasks": tasks,
    }, raw


# strings that must never reach a public trace
PRIVATE = re.compile(r"/home/dogi|/mnt/Disk1|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"
                     r"|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|Bearer [A-Za-z0-9._-]{16,}")


# hidden test names a trace may contain, with the reason it is not a leak
LEAK_OK = {
    ("tomlkit-542", "test_replace_dotted_key_with_aot_keeps_following_sibling"):
        "parent source already has ..._with_table_ and ..._with_empty_table_keeps_following_sibling, "
        "so agents name their own aot test the same way (and cite the wrong issue number).",
}


def hidden_names():
    """task id -> hidden test function names, used only to check for leaks.

    Names that already exist in the parent source the agent gets are skipped:
    reading them from the repo is not a leak.
    """
    names = {}
    for line in (DATASET / "tasks.jsonl").read_text().splitlines():
        t = json.loads(line)
        with tarfile.open(DATASET / t["source_archive"]) as tar:
            src = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile() and m.name.endswith(".py"))
        found = {a.split("::")[-1].split("[")[0] for a in t["fail_to_pass_command"] if "::" in a}
        names[t["id"]] = {n for n in found
                          if not re.search(rb"\bdef " + re.escape(n.encode()) + rb"\b", src)
                          and (t["id"], n) not in LEAK_OK}
    return names


def task_meta():
    meta = {}
    for line in (DATASET / "tasks.jsonl").read_text().splitlines():
        t = json.loads(line)
        meta[t["id"]] = {"repo": t["repository"], "title": t["issue_title"]}
    return meta


def trace(model, entry, run, t, o):
    """One public trace. Keeps what the agent saw and did, drops hidden grader output."""
    tools = t.get("tool_trace") or []
    attempts = []
    # runs that were killed (loop, timeout) keep no per-attempt records, only the task's own totals
    fallback = [{"attempt": 1, **{k: t.get(k) for k in (
        "response", "thinking", "passed", "done_reason", "response_time_s", "model_turns", "input_tokens", "output_tokens")}}]
    for a in t.get("attempts") or fallback:
        n = a.get("attempt", 1)
        attempts.append({
            "attempt": n,
            "passed": bool(a.get("passed")),
            "feedback": a.get("feedback") or "",
            "thinking": a.get("thinking") or "",
            "response": a.get("response") or "",
            "done_reason": a.get("done_reason") or "",
            "secs": round(a.get("response_time_s") or 0),
            "turns": a.get("model_turns") or 0,
            "input_tokens": a.get("input_tokens") or 0,
            "output_tokens": a.get("output_tokens") or 0,
            "tools": [{k: x.get(k) for k in ("name", "arguments", "is_error", "duration_s", "output", "output_truncated")}
                      for x in tools if x.get("attempt", 1) == n],
        })
    ws = t.get("workspace") if isinstance(t.get("workspace"), dict) else {}
    out = {
        "patcheval": RELEASE,
        "model": model["name"], "quant": model["quant"], "where": model["where"],
        "task": t["task_id"], "run": run, "outcome": o,
        "issue": t.get("prompt") or "",
        "secs": round(t.get("response_time_s") or 0),
        "tool_calls": t.get("tool_calls") or 0, "turns": t.get("model_turns") or 0,
        "loop_killed_at_s": t.get("loop_killed_at_s"),
        "stop_reason": t.get("error") if o in ("loop", "timeout") else "",
        "attempts": attempts,
        "patch": ws.get("patch") or "",
        "changed_paths": ws.get("changed_paths") or [],
        "hidden_tests": {"fail_to_pass_exit": ws.get("f2p_exit_code"), "regression_exit": ws.get("regression_exit_code")},
        "note": entry.get("note", "") if t["task_id"] in entry.get("overrides", {}) else "",
    }
    rescore = RESCORES.get(t["task_id"])
    if rescore and run in rescore["runs"]:
        out["hidden_tests"]["fail_to_pass_exit"] = rescore["runs"][run]
        out["note"] = " ".join(x for x in (out["note"], rescore["note"]) if x)
    return out


def write_traces(built, hidden):
    problems = []
    for model, raw, entry in built:
        d = TRACES / model["slug"]
        d.mkdir(parents=True, exist_ok=True)
        for tid, (run, t) in raw.items():
            body = json.dumps(trace(model, entry, run, t, model["tasks"][tid]["o"]), ensure_ascii=False)
            for m in set(PRIVATE.findall(body)):
                problems.append(f"{model['slug']}/{tid}: private string {m[:24]!r}")
            for name in hidden.get(tid, ()):
                if re.search(r"\b" + re.escape(name) + r"\b", body):
                    problems.append(f"{model['slug']}/{tid}: hidden test name {name!r}")
            # mtime=0 keeps the bytes stable, so unchanged traces don't show up in git
            (d / f"{tid}.json.gz").write_bytes(gzip.compress(body.encode(), 9, mtime=0))
    return problems


def main():
    built = [(*build(e), e) for e in ENTRIES]
    models = [m for m, _, _ in built]
    order = list(dict.fromkeys(tid for m in models for tid in m["tasks"]))
    for m in models:
        if len(m["tasks"]) != 20:
            print(f"warning: {m['name']} {m['quant']} covers {len(m['tasks'])} tasks", file=sys.stderr)
    payload = {
        "release": f"{RELEASE} r{REVISION}",
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "task_order": order,
        "task_meta": task_meta(),
        "models": models,
    }
    problems = write_traces(built, hidden_names())
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit(f"{len(problems)} trace problems, nothing published. fix or allowlist them first.")
    OUT.write_text("window.PATCHEVAL = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT} ({len(models)} models, {len(order)} tasks)")
    for m in models:
        print(f"  {m['passed']:>2}/{m['scored']:<2} first {m['first']:>2} loops {m['loops']}  {m['name']} · {m['quant']}")


if __name__ == "__main__":
    main()
