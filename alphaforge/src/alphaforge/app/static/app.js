"use strict";
// AlphaForge UI. Plain JavaScript, no build step. Talks to the local JSON API.

const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "–"
    : typeof v === "number"
      ? Math.abs(v) >= 1000
        ? v.toLocaleString(undefined, { maximumFractionDigits: 0 })
        : v.toFixed(d)
      : esc(v);
const pct = (v) =>
  v === null || v === undefined
    ? "–"
    : (v * 100).toFixed(Math.abs(v) < 0.1 ? 2 : 1) + "%";
const signCls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");

const state = {
  info: null,
  datasets: [],
  dataset: null,
  run: null,
  current: null,
  job: null,
  charts: [],
};

async function api(path, opts = {}) {
  const r = await fetch(
    path,
    opts.body && !(opts.body instanceof FormData)
      ? {
          ...opts,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(opts.body),
        }
      : opts,
  );
  const data = await r.json().catch(() => ({}));
  if (!r.ok)
    throw new Error(
      data.detail
        ? typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail)
        : r.statusText,
    );
  return data;
}

function show(view) {
  document
    .querySelectorAll(".view")
    .forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  document
    .querySelectorAll("#nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  window.dispatchEvent(new Event("resize"));
}
document
  .querySelectorAll("#nav button")
  .forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

// ---------- charts
function css(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}
function lineChart(el, t, series, opts = {}) {
  el.innerHTML = "";
  if (!t || !t.length) {
    el.innerHTML = '<p class="muted">No data.</p>';
    return null;
  }
  const width = el.clientWidth || 800;
  const splitT = opts.splitT;
  const plugins = splitT
    ? [
        {
          hooks: {
            drawClear: (u) => {
              const x0 = u.valToPos(splitT, "x", true);
              const ctx = u.ctx;
              ctx.save();
              ctx.fillStyle = css("--oos");
              ctx.fillRect(
                x0,
                u.bbox.top,
                u.bbox.left + u.bbox.width - x0,
                u.bbox.height,
              );
              ctx.restore();
            },
          },
        },
      ]
    : [];
  const u = new uPlot(
    {
      width,
      height: opts.height || 260,
      plugins,
      scales: { x: { time: true } },
      axes: [
        { stroke: css("--muted"), grid: { stroke: css("--border") } },
        { stroke: css("--muted"), grid: { stroke: css("--border") }, size: 70 },
      ],
      series: [
        {},
        ...series.map((s) => ({
          label: s.label,
          stroke: s.color || css("--line"),
          width: 1.5,
          fill: s.fill,
        })),
      ],
    },
    [t, ...series.map((s) => s.data)],
    el,
  );
  state.charts.push([u, el]);
  return u;
}
window.addEventListener("resize", () => {
  state.charts = state.charts.filter(([u, el]) => document.body.contains(el));
  state.charts.forEach(([u, el]) => {
    if (el.clientWidth) u.setSize({ width: el.clientWidth, height: u.height });
  });
});

// ---------- info
async function loadInfo() {
  state.info = await api("/api/info");
  $("#ver").textContent =
    "v" + state.info.version + (state.info.jit ? " · JIT" : "");
  $("#b-fitness").innerHTML = Object.entries(state.info.fitness)
    .map(
      ([k, v]) =>
        `<option value="${k}" ${k === "return_dd" ? "selected" : ""}>${esc(v)}</option>`,
    )
    .join("");
  $("#b-cats").innerHTML = state.info.categories
    .map(
      (c) =>
        `<label><input type="checkbox" value="${esc(c)}" checked> ${esc(c)}</label>`,
    )
    .join("");
  $("#s-target").innerHTML = Object.entries(state.info.export_targets)
    .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`)
    .join("");
}

// ---------- data
async function loadDatasets(selectId) {
  state.datasets = await api("/api/datasets");
  const box = $("#datasets");
  if (!state.datasets.length)
    box.innerHTML =
      '<p class="muted">No datasets yet. Import a file or create a synthetic dataset.</p>';
  else
    box.innerHTML = state.datasets
      .map((d) => {
        const r = d.report || {};
        const notes = (r.warnings || []).concat(r.fixes || []);
        return `<div class="item" data-id="${esc(d.id)}"><div><strong>${esc(d.name)}</strong> <span class="meta">${esc(d.instrument.symbol)} · ${r.rows} bars · ${esc((r.start || "").slice(0, 10))} → ${esc((r.end || "").slice(0, 10))}${notes.length ? " · " + esc(notes.join("; ")) : ""}</span></div><button data-del="${esc(d.id)}">Delete</button></div>`;
      })
      .join("");
  box.querySelectorAll(".item").forEach((it) =>
    it.addEventListener("click", (e) => {
      if (!e.target.dataset.del) selectDataset(it.dataset.id);
    }),
  );
  box.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("Delete this dataset?")) return;
      await api("/api/datasets/" + b.dataset.del, { method: "DELETE" });
      loadDatasets();
    }),
  );
  $("#b-dataset").innerHTML = state.datasets
    .map(
      (d) =>
        `<option value="${esc(d.id)}">${esc(d.name)} (${d.report.rows} bars)</option>`,
    )
    .join("");
  const pick =
    selectId ||
    (state.dataset && state.dataset.id) ||
    (state.datasets[0] && state.datasets[0].id);
  if (pick) selectDataset(pick);
}

async function selectDataset(id) {
  const d = await api("/api/datasets/" + id);
  state.dataset = d;
  $("#b-dataset").value = id;
  document
    .querySelectorAll("#datasets .item")
    .forEach((it) => it.classList.toggle("selected", it.dataset.id === id));
  if ($("#view-data").classList.contains("active") || true)
    lineChart($("#ds-chart"), d.preview.t, [
      { label: d.instrument.symbol + " close", data: d.preview.close },
    ]);
}

$("#upload").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#upload-msg");
  msg.innerHTML = "Importing…";
  try {
    const meta = await api("/api/datasets", {
      method: "POST",
      body: new FormData(e.target),
    });
    const r = meta.report;
    msg.innerHTML =
      `<p class="ok">Imported ${r.rows} bars.</p>` +
      (r.warnings.length || r.fixes.length
        ? `<p class="warn">${esc(r.warnings.concat(r.fixes).join("; "))}</p>`
        : "");
    loadDatasets(meta.id);
  } catch (err) {
    msg.innerHTML = `<p class="err">${esc(err.message)}</p>`;
  }
});
$("#syn-make").addEventListener("click", async () => {
  const meta = await api("/api/datasets/synthetic", {
    method: "POST",
    body: {
      name: `Synthetic seed ${$("#syn-seed").value}`,
      bars: +$("#syn-bars").value,
      seed: +$("#syn-seed").value,
      mean_reversion: +$("#syn-mr").value,
    },
  });
  loadDatasets(meta.id);
});

// ---------- build
const parseChoices = (s, int) =>
  s
    .split(",")
    .map((x) => x.trim().toLowerCase())
    .filter(Boolean)
    .map((x) => (x === "none" ? null : int ? parseInt(x, 10) : parseFloat(x)))
    .filter((x) => x === null || !Number.isNaN(x));

function backtestCfg() {
  return {
    costs: {
      commission: +$("#b-comm").value,
      slippage_ticks: +$("#b-slip").value,
    },
    initial_capital: +$("#b-capital").value,
    oos_fraction: +$("#b-oos").value / 100,
  };
}

$("#b-start").addEventListener("click", async () => {
  const cats = [...document.querySelectorAll("#b-cats input:checked")].map(
    (i) => i.value,
  );
  const gen = {
    direction: $("#b-direction").value,
    fitness: $("#b-fitness").value,
    max_entry_signals: +$("#b-maxsig").value,
    categories: cats.length === state.info.categories.length ? null : cats,
    min_trades_is: +$("#b-mintis").value,
    min_trades_oos: +$("#b-mintoos").value,
    population: +$("#b-pop").value,
    generations: +$("#b-gens").value,
    seed: +$("#b-seed").value,
    quantity: +$("#b-qty").value,
    stop_atr: parseChoices($("#b-stop").value),
    target_atr: parseChoices($("#b-target").value),
    trail_atr: parseChoices($("#b-trail").value),
    max_bars: parseChoices($("#b-maxbars").value, true),
    use_exit_signals: $("#b-exitsig").checked,
    allow_profitable_close: $("#b-profclose").checked,
  };
  $("#b-msg").textContent = "Starting…";
  try {
    const job = await api("/api/jobs/generate", {
      method: "POST",
      body: {
        dataset_id: $("#b-dataset").value,
        generator: gen,
        backtest: backtestCfg(),
      },
    });
    $("#b-start").disabled = true;
    $("#b-cancel").disabled = false;
    pollJob(
      job.id,
      (j) => {
        const p = j.progress || {};
        if (p.generations !== undefined) {
          $("#b-bar").style.width =
            `${Math.round((100 * (p.generation || 0)) / Math.max(1, p.generations))}%`;
          $("#b-msg").textContent =
            `Generation ${p.generation}/${p.generations} · ${p.evaluated} strategies evaluated · ${p.valid} met the in-sample trade minimum · best fitness ${fmt(p.best_fitness, 3)} · ${fmt(p.elapsed_s, 1)}s`;
        }
      },
      async (j) => {
        $("#b-start").disabled = false;
        $("#b-cancel").disabled = true;
        if (j.status === "error") {
          $("#b-msg").innerHTML = `<span class="err">${esc(j.error)}</span>`;
          return;
        }
        $("#b-bar").style.width = "100%";
        $("#b-msg").textContent =
          `Done: ${j.result.results.length} strategies passed the filters out of ${j.result.evaluated} evaluated.`;
        await loadRuns(j.result.id);
        show("results");
      },
    );
  } catch (err) {
    $("#b-msg").innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
});
$("#b-cancel").addEventListener(
  "click",
  () => state.job && api(`/api/jobs/${state.job}/cancel`, { method: "POST" }),
);

function pollJob(id, onProgress, onDone) {
  state.job = id;
  const tick = async () => {
    let j;
    try {
      j = await api("/api/jobs/" + id);
    } catch (e) {
      $("#jobstatus").textContent = "";
      return;
    }
    $("#jobstatus").textContent =
      j.status === "running" ? `${j.kind} running…` : "";
    if (onProgress) onProgress(j);
    if (["done", "error", "cancelled"].includes(j.status)) {
      onDone(j);
      return;
    }
    setTimeout(tick, 600);
  };
  tick();
}

// ---------- results
async function loadRuns(selectId) {
  const runs = await api("/api/runs");
  $("#r-run").innerHTML = runs
    .map(
      (r) =>
        `<option value="${esc(r.id)}">${new Date(r.created * 1000).toLocaleString()} · ${r.results} results · ${r.evaluated} evaluated</option>`,
    )
    .join("");
  const id = selectId || (runs[0] && runs[0].id);
  if (id) {
    $("#r-run").value = id;
    await loadRun(id);
  }
}
$("#r-run").addEventListener("change", (e) => loadRun(e.target.value));

async function loadRun(id) {
  state.run = await api("/api/runs/" + id);
  $("#r-warning").textContent = state.run.warning || "";
  renderResults("rank", 1);
}

const RCOLS = [
  ["rank", "#", (r) => r.rank],
  ["desc", "Rules", (r) => r.description],
  ["is_trades", "IS trades", (r) => r.metrics.in_sample.trades],
  ["is_pf", "IS PF", (r) => r.metrics.in_sample.profit_factor],
  ["is_net", "IS net", (r) => r.metrics.in_sample.net_profit],
  ["oos_trades", "OOS trades", (r) => r.metrics.out_of_sample.trades],
  ["oos_pf", "OOS PF", (r) => r.metrics.out_of_sample.profit_factor],
  ["oos_net", "OOS net", (r) => r.metrics.out_of_sample.net_profit],
  ["oos_dd", "OOS max DD", (r) => r.metrics.out_of_sample.max_drawdown],
  ["dsr", "Deflated SR", (r) => r.selection.dsr],
];
function renderResults(key, dir) {
  const rows = [...state.run.results].sort((a, b) => {
    const f = RCOLS.find((c) => c[0] === key)[2];
    const va = f(a),
      vb = f(b);
    return (
      (typeof va === "string"
        ? va.localeCompare(vb)
        : (va ?? -1e18) - (vb ?? -1e18)) * dir
    );
  });
  const t = $("#r-table");
  t.innerHTML =
    `<thead><tr>${RCOLS.map((c) => `<th data-k="${c[0]}" class="${c[0] === "desc" ? "l" : ""}">${c[1]}</th>`).join("")}</tr></thead><tbody>` +
    rows
      .map(
        (r) =>
          `<tr data-rank="${r.rank}">${RCOLS.map((c) => {
            const v = c[2](r);
            if (c[0] === "desc") return `<td class="l">${esc(v)}</td>`;
            if (c[0] === "dsr") return `<td>${pct(v)}</td>`;
            if (c[0].endsWith("net"))
              return `<td class="${signCls(v)}">${fmt(v)}</td>`;
            return `<td>${fmt(v, c[0].endsWith("trades") || c[0] === "rank" ? 0 : 2)}</td>`;
          }).join("")}</tr>`,
      )
      .join("") +
    "</tbody>";
  t.querySelectorAll("th").forEach((th) =>
    th.addEventListener("click", () =>
      renderResults(th.dataset.k, th.dataset.k === key ? -dir : -1),
    ),
  );
  t.querySelectorAll("tbody tr").forEach((tr) =>
    tr.addEventListener("click", () => {
      const r = state.run.results.find((x) => x.rank === +tr.dataset.rank);
      openStrategy(r.strategy, state.run.dataset_id, state.run.backtest);
    }),
  );
}

// ---------- strategy
async function openStrategy(strategy, datasetId, bt) {
  state.current = { strategy, datasetId, backtest: bt || backtestCfg() };
  show("strategy");
  $("#s-desc").textContent = "Loading…";
  $("#s-rob-out").innerHTML = '<span class="muted">Not run yet.</span>';
  $("#s-wf-out").innerHTML = '<span class="muted">Not run yet.</span>';
  $("#s-code").textContent = "";
  try {
    const d = await api("/api/backtest", {
      method: "POST",
      body: {
        dataset_id: datasetId,
        strategy,
        backtest: state.current.backtest,
      },
    });
    state.current.result = d;
    renderStrategy(d);
  } catch (err) {
    $("#s-desc").innerHTML = `<span class="err">${esc(err.message)}</span>`;
  }
}

const MROWS = [
  ["trades", "Trades", 0],
  ["net_profit", "Net profit", 2],
  ["profit_factor", "Profit factor", 2],
  ["win_rate", "Win rate", "%"],
  ["avg_trade", "Average trade", 2],
  ["win_loss_ratio", "Avg win / avg loss", 2],
  ["max_drawdown", "Max drawdown", 2],
  ["max_drawdown_pct", "Max drawdown %", "%"],
  ["return_dd", "Net / max DD", 2],
  ["sharpe", "Sharpe (annualised)", 2],
  ["sortino", "Sortino", 2],
  ["cagr", "CAGR", "%"],
  ["sqn", "SQN", 2],
  ["t_stat", "t-statistic", 2],
  ["k_ratio", "K-ratio", 2],
  ["exposure", "Time in market", "%"],
  ["avg_bars", "Avg bars held", 1],
];
function renderStrategy(d) {
  $("#s-desc").textContent = d.description;
  const m = d.metrics;
  const cell = (v, f) => (f === "%" ? pct(v) : fmt(v, f));
  $("#s-metrics").innerHTML =
    `<table><thead><tr><th class="l">Metric</th><th>All</th><th>In-sample</th><th>Out-of-sample</th></tr></thead><tbody>` +
    MROWS.map(
      ([k, label, f]) =>
        `<tr><td class="l">${label}</td><td>${cell(m.all[k], f)}</td><td>${cell(m.in_sample[k], f)}</td><td>${cell(m.out_of_sample[k], f)}</td></tr>`,
    ).join("") +
    "</tbody></table>" +
    `<p class="muted">Out-of-sample starts ${esc((d.split_time || "").slice(0, 10))}. Profit factor 999 means no losing trades.</p>`;
  const splitT = d.split_time ? Date.parse(d.split_time) / 1000 : null;
  lineChart(
    $("#s-equity"),
    d.equity.t,
    [{ label: "Equity", data: d.equity.v }],
    { splitT },
  );
  lineChart(
    $("#s-dd"),
    d.equity.t,
    [
      {
        label: "Drawdown",
        data: d.equity.dd,
        color: css("--dd"),
        fill: css("--oos"),
      },
    ],
    { height: 150, splitT },
  );
  const trades = d.trades.slice(-200).reverse();
  $("#s-trades").innerHTML =
    `<thead><tr><th class="l">Entry</th><th class="l">Exit</th><th>Entry px</th><th>Exit px</th><th>Bars</th><th class="l">Reason</th><th>P&amp;L</th><th>MAE</th><th>MFE</th><th class="l">Sample</th></tr></thead><tbody>` +
    trades
      .map(
        (t) =>
          `<tr><td class="l">${esc(t.entry_time.slice(0, 16))}</td><td class="l">${esc(t.exit_time.slice(0, 16))}</td><td>${fmt(t.entry_price, 4)}</td><td>${fmt(t.exit_price, 4)}</td><td>${t.bars}</td><td class="l">${esc(t.reason)}</td><td class="${signCls(t.pnl)}">${fmt(t.pnl)}</td><td>${fmt(t.mae)}</td><td>${fmt(t.mfe)}</td><td class="l">${t.sample}</td></tr>`,
      )
      .join("") +
    "</tbody>" +
    (d.trades.length > 200
      ? `<caption class="muted">Showing the latest 200 of ${d.trades.length} trades. The CLI writes the full list.</caption>`
      : "");
}

function renderTests(out) {
  const kv = (o) =>
    Object.entries(o || {})
      .filter(([k, v]) => typeof v !== "object")
      .map(
        ([k, v]) => `${esc(k)}: ${typeof v === "number" ? fmt(v, 3) : esc(v)}`,
      )
      .join(" · ");
  const body = (t) => {
    const parts = [];
    for (const [k, v] of Object.entries(t)) {
      if (["test", "verdict", "rule", "rows", "axes"].includes(k)) continue;
      if (v && typeof v === "object" && !Array.isArray(v))
        parts.push(`<div class="kv"><b>${esc(k)}</b> ${kv(v)}</div>`);
      else if (!Array.isArray(v))
        parts.push(
          `<div class="kv"><b>${esc(k)}</b> ${typeof v === "number" ? fmt(v, 3) : esc(v)}</div>`,
        );
    }
    if (t.rows)
      parts.push(t.rows.map((r) => `<div class="kv">${kv(r)}</div>`).join(""));
    return parts.join("");
  };
  return (
    `<p>Passed ${out.score.pass}, warnings ${out.score.warn}, failed ${out.score.fail}. A pass is evidence against overfitting, not a forecast.</p><div class="tests">` +
    out.tests
      .map(
        (t) =>
          `<div class="test"><h4>${esc(t.test.replace(/_/g, " "))} <span class="badge ${t.verdict}">${t.verdict.toUpperCase()}</span></h4>${body(t)}<div class="kv"><i>${esc(t.rule || t.reason || "")}</i></div></div>`,
      )
      .join("") +
    "</div>"
  );
}

async function runRobustness(quick) {
  if (!state.current) return;
  $("#s-rob-out").textContent = "Running robustness tests…";
  const job = await api("/api/jobs/robustness", {
    method: "POST",
    body: {
      dataset_id: state.current.datasetId,
      strategy: state.current.strategy,
      backtest: state.current.backtest,
      quick,
    },
  });
  pollJob(job.id, null, (j) => {
    $("#s-rob-out").innerHTML =
      j.status === "done"
        ? renderTests(j.result)
        : `<span class="err">${esc(j.error || j.status)}</span>`;
  });
}
$("#s-rob-quick").addEventListener("click", () => runRobustness(true));
$("#s-rob").addEventListener("click", () => runRobustness(false));

$("#s-wf").addEventListener("click", async () => {
  if (!state.current) return;
  $("#s-wf-out").textContent = "Running walk-forward analysis…";
  const job = await api("/api/jobs/walkforward", {
    method: "POST",
    body: {
      dataset_id: state.current.datasetId,
      strategy: state.current.strategy,
      backtest: state.current.backtest,
    },
  });
  pollJob(job.id, null, (j) => {
    const box = $("#s-wf-out");
    if (j.status !== "done") {
      box.innerHTML = `<span class="err">${esc(j.error || j.status)}</span>`;
      return;
    }
    const r = j.result;
    box.innerHTML =
      `<p><span class="badge ${r.verdict}">${r.verdict.toUpperCase()}</span> Stitched out-of-sample net ${fmt(r.stitched_oos.net_profit)} over ${r.stitched_oos.trades} trades · efficiency ${fmt(r.walk_forward_efficiency)} · ${r.profitable_windows}/${r.windows.length} windows profitable. <i class="muted">${esc(r.rule)}</i></p>` +
      `<div class="tablewrap"><table><thead><tr><th>#</th><th class="l">OOS period</th><th class="l">Chosen parameters</th><th>OOS trades</th><th>OOS net</th></tr></thead><tbody>` +
      r.windows
        .map(
          (w) =>
            `<tr><td>${w.window}</td><td class="l">${esc(w.oos_start.slice(0, 10))} → ${esc(w.oos_end.slice(0, 10))}</td><td class="l">${esc(JSON.stringify(w.params))}</td><td>${w.oos_trades}</td><td class="${signCls(w.oos_net_profit)}">${fmt(w.oos_net_profit)}</td></tr>`,
        )
        .join("") +
      `</tbody></table></div><div id="wf-chart" class="chart"></div>`;
    lineChart($("#wf-chart"), r.equity.t, [
      { label: "Stitched OOS equity", data: r.equity.v },
    ]);
  });
});

$("#s-export").addEventListener("click", async () => {
  if (!state.current) return;
  try {
    const d = await api("/api/export", {
      method: "POST",
      body: {
        strategy: state.current.strategy,
        target: $("#s-target").value,
        backtest: state.current.backtest,
        dataset_id: state.current.datasetId,
      },
    });
    $("#s-code").textContent = d.code;
    state.current.export = d;
  } catch (err) {
    $("#s-code").textContent = "Error: " + err.message;
  }
});
$("#s-copy").addEventListener(
  "click",
  () =>
    navigator.clipboard &&
    navigator.clipboard.writeText($("#s-code").textContent),
);
$("#s-download").addEventListener("click", () => {
  const e = state.current && state.current.export;
  if (!e) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([e.code], { type: "text/plain" }));
  a.download = `alphaforge_strategy.${e.extension}`;
  a.click();
});

$("#s-save").addEventListener("click", async () => {
  if (!state.current) return;
  const note = prompt("Note for this strategy (optional):", "") ?? "";
  await api("/api/strategies", {
    method: "POST",
    body: {
      dataset_id: state.current.datasetId,
      strategy: state.current.strategy,
      backtest: state.current.backtest,
      note,
      metrics: state.current.result ? state.current.result.metrics : null,
    },
  });
  loadSaved();
});

async function loadSaved() {
  const list = await api("/api/strategies");
  const box = $("#saved");
  box.innerHTML = list.length
    ? list
        .map(
          (s) =>
            `<div class="item" data-id="${esc(s.id)}"><div><strong>${esc(s.note || s.id)}</strong><div class="meta">${esc(s.strategy.direction)} · ${esc(s.strategy.entry.map((e) => e.template).join(", "))}${s.metrics ? ` · OOS net ${fmt(s.metrics.out_of_sample.net_profit)}` : ""}</div></div><button data-del="${esc(s.id)}">Delete</button></div>`,
        )
        .join("")
    : '<p class="muted">Nothing saved yet.</p>';
  box.querySelectorAll(".item").forEach((it) =>
    it.addEventListener("click", (e) => {
      if (e.target.dataset.del) return;
      const s = list.find((x) => x.id === it.dataset.id);
      openStrategy(s.strategy, s.dataset_id, s.backtest);
    }),
  );
  box.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api("/api/strategies/" + b.dataset.del, { method: "DELETE" });
      loadSaved();
    }),
  );
}

(async function init() {
  try {
    await loadInfo();
    await loadDatasets();
    await loadRuns();
    await loadSaved();
  } catch (err) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<p class="err">${esc(err.message)}</p>`,
    );
  }
})();
