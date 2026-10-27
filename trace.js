// PatchEval trace viewer. Opens from any task cell, loads traces/<slug>/<task>.json.gz on demand.
// Deep link: #t/<slug>/<task>
(() => {
  const D = window.PATCHEVAL;
  const META = D.task_meta || {};
  const LABEL = { pass: "Solved first try", repair: "Solved on repair", fail: "Failed", loop: "Killed for looping", timeout: "Timed out", error: "Harness error" };
  const cache = new Map();
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtSecs = s => { s = Math.round(s || 0); if (s < 60) return `${s}s`; const m = Math.round(s / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${m % 60}m`; };
  const fmtTok = n => !n ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`;
  const lines = s => (s || "").split("\n").length;

  const ICON = {
    bash: '<svg viewBox="0 0 16 16"><path d="M3 4.5 6.5 8 3 11.5M8 12h5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    read: '<svg viewBox="0 0 16 16"><path d="M4 1.8h5l3 3v9.4H4z M9 1.8v3h3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M6 8.5h4M6 11h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    edit: '<svg viewBox="0 0 16 16"><path d="M10.5 2.5l3 3L6 13H3v-3z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    write: '<svg viewBox="0 0 16 16"><path d="M4 1.8h5l3 3v9.4H4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M8 7v5M5.5 9.5h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    other: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
  };

  // ---------- tiny markdown for issues, reasoning and final messages ----------
  function md(src) {
    const out = [];
    const parts = String(src || "").split(/^```[^\n]*\n?/m);
    parts.forEach((part, i) => {
      if (i % 2) { out.push(`<pre class="tv-code">${esc(part.replace(/\n$/, ""))}</pre>`); return; }
      part.split(/\n{2,}/).forEach(block => {
        if (!block.trim()) return;
        const inline = t => esc(t).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
        const h = block.match(/^(#{1,4})\s+(.*)$/);
        if (h && !block.includes("\n")) { out.push(`<div class="tv-h">${inline(h[2])}</div>`); return; }
        if (/^\s*([-*]|\d+\.)\s/.test(block)) {
          out.push("<ul>" + block.split(/\n(?=\s*(?:[-*]|\d+\.)\s)/).map(li => `<li>${inline(li.replace(/^\s*(?:[-*]|\d+\.)\s+/, "")).replace(/\n/g, "<br>")}</li>`).join("") + "</ul>");
          return;
        }
        out.push(`<p>${inline(block).replace(/\n/g, "<br>")}</p>`);
      });
    });
    return out.join("");
  }

  // ---------- diffs ----------
  function diffHtml(patch) {
    if (!patch) return "";
    const files = patch.split(/^(?=diff --git )/m).filter(Boolean);
    return files.map(f => {
      const name = (f.match(/^diff --git a\/(\S+)/) || [])[1] || "patch";
      let add = 0, del = 0;
      const body = f.split("\n").filter(l => !/^(diff --git|index |--- |\+\+\+ |new file mode|deleted file mode)/.test(l)).map(l => {
        if (l.startsWith("@@")) return `<div class="dl dh">${esc(l)}</div>`;
        if (l.startsWith("+")) { add++; return `<div class="dl da">${esc(l)}</div>`; }
        if (l.startsWith("-")) { del++; return `<div class="dl dd">${esc(l)}</div>`; }
        return `<div class="dl">${esc(l) || " "}</div>`;
      }).join("");
      return `<div class="tv-file"><div class="tv-fh"><span class="mono">${esc(name)}</span><span class="tv-fs"><b class="a">+${add}</b> <b class="d">−${del}</b></span></div><div class="tv-diff">${body}</div></div>`;
    }).join("");
  }
  // line diff for one edit: LCS over lines, unchanged runs longer than 6 lines are folded
  function editDiff(e) {
    const a = String(e.oldText ?? e.old_string ?? "").split("\n"), b = String(e.newText ?? e.new_string ?? "").split("\n");
    const row = (cls, sign, l) => `<div class="dl ${cls}">${sign}${esc(l)}</div>`;
    if (a.length * b.length > 250000) return `<div class="tv-diff">${a.map(l => row("dd", "-", l)).join("")}${b.map(l => row("da", "+", l)).join("")}</div>`;
    const n = a.length, m = b.length, L = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const ops = [];
    let i = 0, j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && a[i] === b[j]) { ops.push([" ", a[i]]); i++; j++; }
      else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) ops.push(["+", b[j++]]);
      else ops.push(["-", a[i++]]);
    }
    let h = "", k = 0;
    while (k < ops.length) {
      if (ops[k][0] !== " ") { h += row(ops[k][0] === "+" ? "da" : "dd", ops[k][0], ops[k][1]); k++; continue; }
      let r = k; while (r < ops.length && ops[r][0] === " ") r++;
      const run = ops.slice(k, r), head = k === 0 ? 0 : 3, tail = r === ops.length ? 0 : 3;
      if (run.length > head + tail + 2) {
        run.slice(0, head).forEach(o => h += row("", " ", o[1]));
        h += `<div class="dl dh">⋯ ${run.length - head - tail} unchanged lines</div>`;
        run.slice(run.length - tail).forEach(o => h += row("", " ", o[1]));
      } else run.forEach(o => h += row("", " ", o[1]));
      k = r;
    }
    return `<div class="tv-diff">${h}</div>`;
  }

  // ---------- one tool call ----------
  function toolSummary(t) {
    const a = t.arguments || {};
    if (t.name === "bash") return `<span class="mono">${esc((a.command || "").split("\n")[0].slice(0, 160))}</span>`;
    if (t.name === "read") return `<span class="mono">${esc(a.path || "")}</span>${a.offset ? `<span class="tv-dim"> · from line ${a.offset}</span>` : ""}`;
    if (t.name === "edit") { const n = (a.edits || [a]).length; return `<span class="mono">${esc(a.path || "")}</span><span class="tv-dim"> · ${n} edit${n > 1 ? "s" : ""}</span>`; }
    if (t.name === "write") return `<span class="mono">${esc(a.path || "")}</span><span class="tv-dim"> · ${lines(a.content)} lines</span>`;
    return `<span class="mono">${esc(JSON.stringify(a).slice(0, 140))}</span>`;
  }
  function toolBody(t) {
    const a = t.arguments || {};
    let h = "";
    if (t.name === "bash") h += `<div class="tv-lbl">command</div><pre class="tv-code">${esc(a.command)}</pre>`;
    else if (t.name === "edit") h += (a.edits || [a]).map((e, i, all) => `<div class="tv-lbl">${all.length > 1 ? `edit ${i + 1} of ${all.length}` : "edit"}</div>${editDiff(e)}`).join("");
    else if (t.name === "write") h += `<div class="tv-lbl">new file content</div><pre class="tv-code">${esc(a.content)}</pre>`;
    else if (t.name !== "read") h += `<div class="tv-lbl">arguments</div><pre class="tv-code">${esc(JSON.stringify(a, null, 2))}</pre>`;
    if (t.output) h += `<div class="tv-lbl">${t.is_error ? "error output" : "output"}${t.output_truncated ? ' <span class="tv-dim">· trimmed to the last 8,000 characters by the harness</span>' : ""}</div><pre class="tv-code${t.is_error ? " err" : ""}">${esc(t.output)}</pre>`;
    else h += `<div class="tv-lbl tv-dim">no output</div>`;
    return h;
  }

  // ---------- panel ----------
  const el = document.createElement("div");
  el.id = "tv-root";
  el.innerHTML = `<div class="tv-back"></div><aside class="tv" role="dialog" aria-modal="true" aria-label="Agent trace"><div class="tv-in"></div></aside>`;
  document.body.appendChild(el);
  const panel = el.querySelector(".tv-in");
  let cur = null, tab = "timeline";

  const order = () => D.task_order;
  function open(slug, task, push = true) {
    const m = D.models.find(x => x.slug === slug);
    if (!m || !m.tasks[task]) return;
    cur = { m, task, slug };
    document.documentElement.classList.add("tv-open");
    el.classList.add("on");
    if (push) history.replaceState(null, "", `#t/${slug}/${task}`);
    head(null);
    body(`<div class="tv-loading"><span></span><span></span><span></span></div>`);
    load(slug, task).then(d => { if (cur && cur.slug === slug && cur.task === task) { cur.d = d; head(d); show(); } })
      .catch(() => body(`<div class="tv-empty">Could not load this trace. Try again in a moment.</div>`));
  }
  function close() {
    el.classList.remove("on");
    document.documentElement.classList.remove("tv-open");
    cur = null;
    history.replaceState(null, "", location.pathname + location.search);
  }
  async function load(slug, task) {
    const key = `${slug}/${task}`;
    if (cache.has(key)) return cache.get(key);
    const r = await fetch(`traces/${slug}/${task}.json.gz`);
    if (!r.ok) throw new Error(r.status);
    const buf = new Uint8Array(await r.arrayBuffer());
    // the host may or may not have decoded the gzip already
    const text = buf[0] === 0x1f && buf[1] === 0x8b
      ? await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
      : new TextDecoder().decode(buf);
    const d = JSON.parse(text);
    cache.set(key, d);
    return d;
  }

  function head(d) {
    const { m, task } = cur;
    const o = m.tasks[task].o, meta = META[task] || {};
    const i = order().indexOf(task);
    const stats = d ? [
      ["Time", fmtSecs(d.secs)], ["Tool calls", d.tool_calls], ["Turns", d.turns],
      ["Tokens in", fmtTok(d.attempts.reduce((s, a) => s + a.input_tokens, 0))],
      ["Tokens out", fmtTok(d.attempts.reduce((s, a) => s + a.output_tokens, 0))],
      ["Attempts", d.attempts.length],
    ] : [];
    panel.querySelector(".tv-head")?.remove();
    panel.insertAdjacentHTML("afterbegin", `<header class="tv-head">
      <div class="tv-bar">
        <div class="tv-crumbs"><span class="tv-pill ${o}"><i></i>${LABEL[o]}</span><span class="mono tv-task">${esc(task)}</span>${meta.repo ? `<a class="tv-repo" href="https://github.com/${esc(meta.repo)}" target="_blank" rel="noopener">${esc(meta.repo)} ↗</a>` : ""}</div>
        <div class="tv-acts">
          <button class="tv-btn" data-a="prev" title="Previous task (←)" ${i <= 0 ? "disabled" : ""}>‹</button>
          <button class="tv-btn" data-a="next" title="Next task (→)" ${i >= order().length - 1 ? "disabled" : ""}>›</button>
          <button class="tv-btn" data-a="link" title="Copy link to this trace"><svg viewBox="0 0 16 16"><path d="M6.5 9.5l3-3M7 4.5l1-1a2.8 2.8 0 014 4l-1 1M9 11.5l-1 1a2.8 2.8 0 01-4-4l1-1" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>
          <button class="tv-btn tv-dl" data-a="dl" title="Download trace as JSON" ${d ? "" : "disabled"}><svg viewBox="0 0 16 16"><path d="M8 2v8M4.5 6.8 8 10.3l3.5-3.5M3 13.5h10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg><span>JSON</span></button>
          <button class="tv-btn" data-a="close" title="Close (Esc)">✕</button>
        </div>
      </div>
      <h3 class="tv-title">${esc(meta.title || task)}</h3>
      <div class="tv-model"><span class="swatch" style="background:${(window.PE_COLORS && window.PE_COLORS(m.color)[0]) || "var(--accent)"}"></span><b>${esc(m.name)}</b><span class="tv-dim">${esc(m.quant)}</span></div>
      ${stats.length ? `<div class="tv-stats">${stats.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("")}</div>` : ""}
      <nav class="tv-tabs">${[["timeline", "Timeline"], ["reasoning", "Reasoning"], ["patch", "Final patch"], ["issue", "Issue"]].map(([k, v]) => `<button data-tab="${k}" aria-selected="${k === tab}">${v}</button>`).join("")}</nav>
    </header>`);
  }
  function body(html) {
    panel.querySelector(".tv-body")?.remove();
    panel.insertAdjacentHTML("beforeend", `<div class="tv-body">${html}</div>`);
  }

  function show() {
    const d = cur.d;
    panel.querySelectorAll(".tv-tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.tab === tab));
    let h = "";
    const o = d.outcome;
    if (d.note) h += `<div class="tv-callout">${esc(d.note)}</div>`;
    if (tab === "timeline") {
      const jump = d.attempts.some(a => a.thinking) ? `<button class="tv-link" data-jump>Jump to the loop in the reasoning →</button>` : "";
      if (o === "loop") h += `<div class="tv-callout bad"><b>Killed for looping${d.loop_killed_at_s ? ` after ${fmtSecs(d.loop_killed_at_s)}` : ""}.</b> The reasoning collapsed into repeating itself, so BenchKit stopped it. ${jump}</div>`;
      if (o === "timeout") h += `<div class="tv-callout warn"><b>Timed out.</b> The agent was still working when the time limit hit.</div>`;
      d.attempts.forEach((a, ai) => {
        const last = ai === d.attempts.length - 1;
        const res = a.passed ? `<span class="tv-chip ok">hidden tests passed</span>` : last ? `<span class="tv-chip no">not fixed</span>` : `<span class="tv-chip no">not fixed, repair turn sent</span>`;
        h += `<div class="tv-att"><div class="tv-atth"><b>${d.attempts.length > 1 ? `Attempt ${a.attempt}` : "Agent run"}</b>${res}<span class="tv-dim">${fmtSecs(a.secs)} · ${a.tools.length} tool calls · ${a.turns} turns</span></div>`;
        if (!a.tools.length) h += `<div class="tv-empty small">No tool calls were recorded for this attempt${o === "loop" || o === "timeout" ? " (the run was stopped before Pi reported them)" : ""}.</div>`;
        h += `<ol class="tv-steps">` + a.tools.map((t, ti) => `<li class="tv-step${t.is_error ? " err" : ""}" data-at="${ai}" data-ti="${ti}">
          <details><summary><span class="tv-ico ${ICON[t.name] ? t.name : "other"}">${ICON[t.name] || ICON.other}</span><span class="tv-tn">${esc(t.name)}</span><span class="tv-sum">${toolSummary(t)}</span><span class="tv-meta">${t.is_error ? '<span class="tv-chip no">error</span>' : ""}${t.duration_s != null ? `${t.duration_s < 1 ? `${Math.round(t.duration_s * 1000)}ms` : `${t.duration_s.toFixed(1)}s`}` : ""}</span></summary><div class="tv-detail"></div></details></li>`).join("") + `</ol>`;
        if (a.response) h += `<div class="tv-final"><div class="tv-lbl">${a.tools.length ? "final message from the agent" : "everything the agent wrote, joined (the harness kept no per-turn split)"}</div><div class="tv-prose">${md(a.response)}</div></div>`;
        if (!a.passed && !last && a.feedback) h += `<div class="tv-repair"><div class="tv-lbl">repair prompt sent back to the agent</div>${esc(a.feedback)}</div>`;
        h += `</div>`;
      });
    } else if (tab === "reasoning") {
      const any = d.attempts.some(a => a.thinking);
      if (!any) h += `<div class="tv-empty">No reasoning was recorded for this run. The endpoint returned no reasoning text.</div>`;
      d.attempts.forEach(a => {
        if (!a.thinking) return;
        h += `<div class="tv-att"><div class="tv-atth"><b>${d.attempts.length > 1 ? `Attempt ${a.attempt}` : "Reasoning"}</b><span class="tv-dim">${a.thinking.length.toLocaleString()} characters${a.thinking.length === 131072 ? " · the harness keeps only the last 131,072" : ""}</span></div><div class="tv-prose tv-think">${md(a.thinking)}</div></div>`;
      });
      if (any) h += `<p class="tv-foot">Reasoning is stored per attempt as one block, so it is shown here next to the timeline, not interleaved with each tool call.</p>`;
    } else if (tab === "patch") {
      const ht = d.hidden_tests || {};
      const st = (code, label) => code == null ? "" : `<div class="tv-test ${code === 0 ? "ok" : "no"}"><i></i><span>${label}</span><b>${code === 0 ? "passed" : `failed (exit ${code})`}</b></div>`;
      h += `<div class="tv-tests">${st(ht.fail_to_pass_exit, "hidden fail-to-pass tests")}${st(ht.regression_exit, "regression suite")}</div>`;
      h += d.patch ? diffHtml(d.patch) : `<div class="tv-empty">The agent left no changes in the repository.</div>`;
      h += `<p class="tv-foot">This is the agent's own diff against the parent commit. The hidden tests themselves are not published.</p>`;
    } else {
      h += `<div class="tv-prose tv-issue">${md(d.issue)}</div>`;
    }
    body(h);
  }

  // ---------- events ----------
  panel.addEventListener("click", e => {
    if (e.target.closest("[data-jump]")) { tab = "reasoning"; show(); panel.scrollTop = panel.scrollHeight; return; }
    const tb = e.target.closest("[data-tab]");
    if (tb) { tab = tb.dataset.tab; show(); panel.scrollTop = 0; return; }
    const b = e.target.closest("[data-a]");
    if (!b || b.disabled) return;
    const a = b.dataset.a, i = order().indexOf(cur.task);
    if (a === "close") close();
    else if (a === "prev" && i > 0) open(cur.slug, order()[i - 1]);
    else if (a === "next" && i < order().length - 1) open(cur.slug, order()[i + 1]);
    else if (a === "link") { navigator.clipboard?.writeText(location.href).then(() => { b.classList.add("done"); setTimeout(() => b.classList.remove("done"), 1200); }).catch(() => {}); }
    else if (a === "dl" && cur.d) {
      const url = URL.createObjectURL(new Blob([JSON.stringify(cur.d, null, 2)], { type: "application/json" }));
      Object.assign(document.createElement("a"), { href: url, download: `patcheval-${cur.task}-${cur.slug}.json` }).click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    }
  });
  // fill a tool call's body only when it is opened: some traces have 100+ calls with long outputs
  panel.addEventListener("toggle", e => {
    const det = e.target;
    if (!det.open) return;
    const li = det.closest(".tv-step"), box = det.querySelector(".tv-detail");
    if (box && !box.dataset.ok) { box.innerHTML = toolBody(cur.d.attempts[+li.dataset.at].tools[+li.dataset.ti]); box.dataset.ok = 1; }
  }, true);
  el.querySelector(".tv-back").onclick = close;
  document.addEventListener("keydown", e => {
    if (!cur) return;
    if (e.key === "Escape") close();
    if (e.target.closest("input,textarea")) return;
    const i = order().indexOf(cur.task);
    if (e.key === "ArrowLeft" && i > 0) open(cur.slug, order()[i - 1]);
    if (e.key === "ArrowRight" && i < order().length - 1) open(cur.slug, order()[i + 1]);
  });
  document.addEventListener("click", e => {
    const c = e.target.closest(".cell[data-t]");
    if (!c) return;
    e.stopPropagation();
    open(c.dataset.s, c.dataset.t);
  }, true);
  const fromHash = () => { const m = location.hash.match(/^#t\/([^/]+)\/(.+)$/); if (m) open(m[1], decodeURIComponent(m[2]), false); };
  window.addEventListener("hashchange", fromHash);
  fromHash();
})();
