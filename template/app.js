/* DataReview client: renders REVIEW_CONFIG + records. No external dependencies. */
(function () {
  "use strict";

  const CFG = window.REVIEW_CONFIG || {};
  const LS_KEY = "datareview:" + (CFG.data_key || CFG.title || "dev");
  const LANG_KEY = "fairyview:lang";

  /* ---------- i18n: every visible string goes through t() ---------- */

  const I18N = {
    en: {
      search: "Search", search_hint: "id / text", view: "View", cards: "Cards", table: "Table",
      layout: "Panel layout", side_by_side: "Side by side", stacked: "Stacked", toggle: "Toggle",
      blind_on: "Hide scores, read text first", blind_off: "Show scores",
      storage_note: "Decisions are kept in this browser's localStorage; export them as JSONL below.",
      export: "Export decisions.jsonl", clear: "Clear decisions on this page",
      chars: "chars", decision: "Decision", keep: "Keep", drop: "Drop", unsure: "Unsure",
      marked: "Marked: ", all: "All", records: "records", shown: "showing {n}",
      load_more: "Load {n} more", generated: "generated", source: "Source: ",
      more_files: " and {n} files in total", dropped: "dropped {n} rows ({detail})",
      no_drops: "read {n} rows, none dropped", caveats: "Read this first",
      load_failed: "Failed to load: ",
    },
    zh: {
      search: "搜索", search_hint: "id / 文本内容", view: "视图", cards: "卡片", table: "表格",
      layout: "面板布局", side_by_side: "并排", stacked: "上下", toggle: "切换",
      blind_on: "隐藏分数，先看文本", blind_off: "显示分数",
      storage_note: "决策保存在浏览器 localStorage；可用下方按钮导出 JSONL。",
      export: "导出 decisions.jsonl", clear: "清除本页决策",
      chars: "字符", decision: "决策", keep: "保留", drop: "剔除", unsure: "存疑",
      marked: "已标记：", all: "全部", records: "条", shown: "已显示 {n}",
      load_more: "再加载 {n} 条", generated: "生成于", source: "来源：",
      more_files: " 等 {n} 个文件", dropped: "丢弃 {n} 行（{detail}）",
      no_drops: "读取 {n} 行，无丢弃", caveats: "读之前先看",
      load_failed: "加载失败：",
    },
  };

  function pickLang() {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved && I18N[saved]) return saved;
    if (CFG.lang && I18N[CFG.lang]) return CFG.lang;
    return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  let lang = pickLang();

  function t(key, vars) {
    let text = (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key;
    for (const [k, v] of Object.entries(vars || {})) text = text.replace("{" + k + "}", v);
    return text;
  }

  function applyStaticText() {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    const blind = document.getElementById("blind");
    if (blind) blind.textContent = state.blind ? t("blind_off") : t("blind_on");
  }
  const state = {
    records: [],
    filtered: [],
    search: "",
    facetValues: {},
    view: "cards",
    layout: CFG.panel_layout || "side_by_side",
    blind: Boolean(CFG.blinded_default),
    decisions: loadDecisions(),
    pageSize: Number(CFG.page_size || 100),
    shown: 0,
  };

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ---------- data loading ---------- */

  function loadRecords() {
    if (window.REVIEW_RECORDS) return Promise.resolve(window.REVIEW_RECORDS);
    const index = window.REVIEW_SHARD_INDEX;
    if (!index) return Promise.resolve([]);
    // Dynamic <script> injection works under file:// where fetch is blocked.
    const loads = index.shards.map(
      (src, i) =>
        new Promise((resolve, reject) => {
          if (window["REVIEW_SHARD_" + i]) return resolve(window["REVIEW_SHARD_" + i]);
          const tag = document.createElement("script");
          tag.src = src;
          tag.onload = () => resolve(window["REVIEW_SHARD_" + i] || []);
          tag.onerror = () => reject(new Error("failed to load " + src));
          document.head.appendChild(tag);
        })
    );
    return Promise.all(loads).then((chunks) => chunks.flat());
  }

  /* ---------- decisions ---------- */

  function loadDecisions() {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    } catch (e) {
      return {};
    }
  }

  function saveDecisions() {
    localStorage.setItem(LS_KEY, JSON.stringify(state.decisions));
  }

  function setDecision(id, value) {
    if (state.decisions[id] === value) delete state.decisions[id];
    else state.decisions[id] = value;
    saveDecisions();
    render();
  }

  /* ---------- span rendering ---------- */

  function renderText(panel) {
    const text = panel.text || "";
    const spans = (panel.spans || []).slice().sort((a, b) => a.start - b.start || b.end - a.end);
    let html = "";
    let cursor = 0;
    for (const span of spans) {
      const start = Math.max(span.start, cursor);
      const end = Math.min(span.end, text.length);
      if (end <= start) continue;
      html += esc(text.slice(cursor, start));
      const label = span.label ? ' title="' + esc(span.label) + '"' : "";
      html += '<mark class="k-' + esc(span.kind) + '"' + label + ">" + esc(text.slice(start, end)) + "</mark>";
      cursor = end;
    }
    html += esc(text.slice(cursor));
    return html;
  }

  /* ---------- scores ---------- */

  function renderScores(record) {
    if (!record.scores || !record.scores.length) return "";
    const items = record.scores.map((s) => {
      const scaleClass = "scale-" + String(s.scale || "0-1").replace(/[^0-9a-z.-]/gi, "-");
      const incomparable = s.comparable === false ? " incomparable" : "";
      let bar = "";
      if (typeof s.value === "number") {
        const max = s.scale === "1-5" ? 5 : 1;
        const pct = Math.max(0, Math.min(100, (100 * s.value) / max));
        bar = '<div class="bar"><i style="width:' + pct.toFixed(2) + '%"></i></div>';
      }
      const reason = s.reason ? '<div class="reason">' + esc(s.reason) + "</div>" : "";
      const shown = typeof s.value === "number" ? s.value.toFixed(s.scale === "1-5" ? 0 : 4) : esc(s.value);
      return (
        '<div class="score ' + scaleClass + incomparable + '"><b>' +
        esc(s.model) + ": " + shown + (s.scale === "1-5" ? " / 5" : "") +
        "</b>" + bar + reason + "</div>"
      );
    });
    return '<div class="scores">' + items.join("") + "</div>";
  }

  /* ---------- record rendering ---------- */

  function renderFields(record) {
    if (!record.fields || !record.fields.length) return "";
    const items = record.fields
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => "<span><b>" + esc(k) + "</b>: " + esc(typeof v === "object" ? JSON.stringify(v) : v) + "</span>");
    return '<div class="fields">' + items.join("") + "</div>";
  }

  function renderPanels(record) {
    if (!record.panels || !record.panels.length) return "";
    const tabs =
      state.layout === "toggle" && record.panels.length > 1
        ? '<div class="toggle-tabs">' +
          record.panels
            .map((p, i) => '<button type="button" data-toggle="' + i + '">' + esc(p.label) + "</button>")
            .join("") +
          "</div>"
        : "";
    const panels = record.panels
      .map(
        (p, i) =>
          '<div class="panel" data-panel="' + i + '"' + (state.layout === "toggle" && i > 0 ? " hidden" : "") + ">" +
          '<h4><span>' + esc(p.label) + "</span><span>" + (p.text || "").length.toLocaleString() + " " + t("chars") + "</span></h4>" +
          "<pre>" + renderText(p) + "</pre></div>"
      )
      .join("");
    return tabs + '<div class="panels ' + esc(state.layout) + '">' + panels + "</div>";
  }

  function renderDecision(record) {
    const current = state.decisions[record.id];
    const btn = (value, label, cls) =>
      '<button type="button" data-decide="' + value + '" class="' + (current === value ? cls : "") + '">' + label + "</button>";
    return (
      '<div class="decision"><span class="small">' + t("decision") + "</span>" +
      btn("keep", t("keep"), "sel-keep") + btn("drop", t("drop"), "sel-drop") + btn("unsure", t("unsure"), "sel-unsure") +
      (current ? '<span class="small">' + t("marked") + esc(t(current)) + "</span>" : "") +
      "</div>"
    );
  }

  function renderCard(record) {
    const badges = Object.entries(record.facets || {})
      .map(([k, v]) => '<span class="badge">' + esc(k) + "=" + esc(v) + "</span>")
      .join("");
    return (
      '<article class="record" id="rec-' + esc(record.id) + '" data-id="' + esc(record.id) + '">' +
      '<div class="record-head"><h3>' + esc(record.id) + '</h3><div class="badges">' + badges + "</div></div>" +
      renderFields(record) +
      renderScores(record) +
      renderPanels(record) +
      renderDecision(record) +
      "</article>"
    );
  }

  function renderTable(rows) {
    const head =
      "<tr><th>id</th><th>facets</th><th>text</th><th>" + t("decision") + "</th></tr>";
    const body = rows
      .map((r) => {
        const text = (r.panels && r.panels[0] ? r.panels[0].text : "").slice(0, 400);
        const facets = Object.entries(r.facets || {}).map(([k, v]) => k + "=" + v).join(" · ");
        return (
          "<tr><td>" + esc(r.id) + "</td><td>" + esc(facets) + '</td><td class="text"><div>' + esc(text) +
          "</div></td><td>" + esc(state.decisions[r.id] || "") + "</td></tr>"
        );
      })
      .join("");
    return '<table class="records"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  }

  /* ---------- filtering ---------- */

  function matches(record) {
    if (state.search) {
      const hay = (record.id + " " + (record.panels || []).map((p) => p.text).join(" ")).toLowerCase();
      if (!hay.includes(state.search)) return false;
    }
    for (const [name, value] of Object.entries(state.facetValues)) {
      if (value && String(record.facets ? record.facets[name] : "") !== value) return false;
    }
    return true;
  }

  function facetValues() {
    const values = {};
    for (const name of CFG.facets || []) {
      const seen = new Set();
      for (const record of state.records) {
        const v = record.facets ? record.facets[name] : undefined;
        if (v !== undefined && v !== null) seen.add(String(v));
      }
      values[name] = Array.from(seen).sort();
    }
    return values;
  }

  function renderFacetControls() {
    const host = document.getElementById("facets");
    if (!host) return;
    const values = facetValues();
    host.innerHTML = Object.entries(values)
      .filter(([, list]) => list.length > 1 && list.length <= 40)
      .map(([name, list]) => {
        const opts = ['<option value="">' + t("all") + "</option>"]
          .concat(list.map((v) => '<option value="' + esc(v) + '">' + esc(v) + "</option>"))
          .join("");
        return '<label class="small">' + esc(name) + ' <select data-facet="' + esc(name) + '">' + opts + "</select></label>";
      })
      .join("");
    host.querySelectorAll("select[data-facet]").forEach((sel) => {
      sel.value = state.facetValues[sel.dataset.facet] || "";
      sel.addEventListener("change", () => {
        state.facetValues[sel.dataset.facet] = sel.value;
        render(true);
      });
    });
  }

  /* ---------- render ---------- */

  function render(reset) {
    if (reset) state.shown = state.pageSize;
    if (!state.shown) state.shown = state.pageSize;
    state.filtered = state.records.filter(matches);
    const host = document.getElementById("records");
    const visible = state.filtered.slice(0, state.shown);
    host.innerHTML =
      state.view === "table" ? renderTable(visible) : visible.map(renderCard).join("");
    const count = document.getElementById("count");
    if (count) {
      const more = state.filtered.length > visible.length ? " (" + t("shown", { n: visible.length }) + ")" : "";
      count.textContent = state.filtered.length + " / " + state.records.length + " " + t("records") + more;
    }
    const moreBtn = document.getElementById("more");
    if (moreBtn) {
      moreBtn.hidden = state.filtered.length <= visible.length;
      moreBtn.textContent = t("load_more", { n: Math.min(state.pageSize, state.filtered.length - visible.length) });
    }
    document.body.classList.toggle("blind", state.blind);
  }

  function bindControls() {
    const search = document.getElementById("search");
    let searchTimer = null;
    search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.search = search.value.trim().toLowerCase();
        render(true);
      }, 150);
    });
    const view = document.getElementById("view");
    view.value = state.view;
    view.addEventListener("change", () => {
      state.view = view.value;
      render(true);
    });
    const layout = document.getElementById("layout");
    layout.value = state.layout;
    layout.addEventListener("change", () => {
      state.layout = layout.value;
      render();
    });
    const blind = document.getElementById("blind");
    blind.addEventListener("click", () => {
      state.blind = !state.blind;
      applyStaticText();
      render();
    });
    const langSelect = document.getElementById("lang");
    if (langSelect) {
      langSelect.value = lang;
      langSelect.addEventListener("change", () => {
        lang = langSelect.value;
        localStorage.setItem(LANG_KEY, lang);
        applyStaticText();
        renderHeader();
        renderFacetControls();
        render();
      });
    }
    document.getElementById("records").addEventListener("click", (event) => {
      const decide = event.target.closest("[data-decide]");
      if (decide) {
        const article = decide.closest("article");
        const id = article ? article.dataset.id : decide.dataset.id;
        if (id) setDecision(id, decide.dataset.decide);
        return;
      }
      const toggle = event.target.closest("[data-toggle]");
      if (toggle) {
        const index = Number(toggle.dataset.toggle);
        const panels = toggle.closest("article").querySelectorAll(".panel");
        panels.forEach((p) => {
          p.hidden = Number(p.dataset.panel) !== index;
        });
      }
    });
    const more = document.getElementById("more");
    if (more) more.addEventListener("click", () => { state.shown += state.pageSize; render(); });
    document.getElementById("export").addEventListener("click", () => {
      const lines = Object.entries(state.decisions).map(([id, decision]) =>
        JSON.stringify({ id, decision, config_hash: CFG.config_hash })
      );
      const blob = new Blob([lines.join("\n") + "\n"], { type: "application/jsonl" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "decisions.jsonl";
      a.click();
      URL.revokeObjectURL(a.href);
    });
    document.getElementById("clear").addEventListener("click", () => {
      state.decisions = {};
      saveDecisions();
      render();
    });
  }

  function renderHeader() {
    const meta = document.getElementById("meta");
    meta.textContent =
      "config " + (CFG.config_hash || "-") + " · " + (CFG.record_count || state.records.length) +
      " " + t("records") + " · " + t("generated") + " " + (CFG.generated_at || "-") + " · schema v" + (CFG.schema_version || "-");
    document.getElementById("description").textContent = CFG.description || "";

    // Provenance first: what file this page came from, and what was dropped.
    // A page that hides either is not reviewable.
    const files = CFG.source_files || [];
    const dropped = CFG.dropped || {};
    const dropTotal = Object.values(dropped).reduce((a, b) => a + b, 0);
    const bits = [];
    if (files.length) {
      const names = files.map((f) => f.path + (f.bytes != null ? " (" + f.bytes + " B)" : ""));
      bits.push(t("source") + names.slice(0, 3).join(", ") + (names.length > 3 ? t("more_files", { n: names.length }) : ""));
    }
    if (dropTotal) {
      const detail = Object.entries(dropped).map(([k, v]) => k + "=" + v).join(", ");
      bits.push(t("dropped", { n: dropTotal, detail: detail }));
    } else if (CFG.rows_examined != null) {
      bits.push(t("no_drops", { n: CFG.rows_examined }));
    }
    const prov = document.getElementById("provenance");
    if (prov && bits.length) {
      prov.hidden = false;
      prov.textContent = bits.join(" · ");
      if (dropTotal) prov.className = "warning";
    }
    const caveats = CFG.caveats || [];
    const box = document.getElementById("caveats");
    if (caveats.length) {
      box.hidden = false;
      box.innerHTML = "<b>" + t("caveats") + "</b><ul>" + caveats.map((c) => "<li>" + esc(c) + "</li>").join("") + "</ul>";
    }
  }

  loadRecords()
    .then((records) => {
      state.records = records;
      applyStaticText();
      renderHeader();
      renderFacetControls();
      bindControls();
      render();
    })
    .catch((err) => {
      document.getElementById("records").innerHTML =
        '<p class="warning">' + t("load_failed") + esc(err.message) + "</p>";
    });
})();
