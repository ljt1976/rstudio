/* PriceHunt 演示页：纯原生 JS，无构建、无外部依赖 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const PLATFORM = {
    jd: { name: "京东", color: "#e1251b" },
    tb: { name: "淘宝", color: "#f08200" },
    pdd: { name: "拼多多", color: "#c026a3" },
  };
  const STEP_KEYS = ["fetch", "clean", "group", "insight"];
  const state = {
    payload: null,
    platformFilter: "",
    sort: "price",
    query: "",
    trendGeom: null,
    bubbleGeom: null,
  };
  let pipelineTimer = null;

  /* ---------------- 工具 ---------------- */
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));

  const num = (value) =>
    Number(value ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (value) => `¥${num(value)}`;
  const salesText = (value) => (value >= 10000 ? `${(value / 10000).toFixed(1)}万` : `${value}`);
  const truncate = (text, length) => (text.length > length ? `${text.slice(0, length)}…` : text);

  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("err", isError);
    el.classList.add("on");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.remove("on"), 3200);
  }

  function setLoading(loading) {
    document.body.classList.toggle("loading", loading);
    $("#progressBar").classList.toggle("on", loading);
    const btn = $("#runBtn");
    btn.disabled = loading;
    $("#runBtnText").textContent = loading ? "采集中" : "开始采集";
    $("#runBtnArrow").innerHTML = loading
      ? '<span class="spinner"></span>'
      : "→";
  }

  function setStatus(loading, payload) {
    const el = $("#sourceStatus");
    el.classList.remove("demo", "warn");
    if (loading) {
      el.innerHTML = "<i></i>正在采集…";
      return;
    }
    if (!payload) return;
    if (payload.meta.fallback) {
      el.classList.add("warn");
      el.innerHTML = "<i></i>实时失败 · 已降级";
    } else if (payload.meta.is_demo) {
      el.classList.add("demo");
      el.innerHTML = "<i></i>演示数据源 · 示例结果";
    } else {
      el.innerHTML = "<i></i>实时数据源";
    }
  }

  /* ---------------- 采集流水线动画 ---------------- */
  function resetPipeline() {
    STEP_KEYS.forEach((key) => {
      const step = $(`.step[data-step="${key}"]`);
      step.classList.remove("active", "running");
      step.querySelector(".step-num b").textContent = "↗";
      step.querySelector("[data-detail]").textContent = "排队中…";
    });
  }

  function startPipeline() {
    clearInterval(pipelineTimer);
    resetPipeline();
    let index = 0;
    const mark = () => {
      STEP_KEYS.forEach((key, i) => {
        const step = $(`.step[data-step="${key}"]`);
        const detail = step.querySelector("[data-detail]");
        step.classList.toggle("running", i === index);
        step.classList.toggle("active", i <= index);
        if (i < index) detail.textContent = "完成";
        if (i === index) detail.textContent = ["正在请求平台…", "标准化与去重…", "型号对齐中…", "计算评分与趋势…"][i];
      });
      index = Math.min(index + 1, STEP_KEYS.length - 1);
    };
    mark();
    pipelineTimer = setInterval(mark, 480);
  }

  function finishPipeline(stages) {
    clearInterval(pipelineTimer);
    (stages || []).forEach((stage) => {
      const step = $(`.step[data-step="${stage.key}"]`);
      if (!step) return;
      step.classList.remove("running");
      step.classList.add("active");
      step.querySelector(".step-num b").textContent = "✓";
      step.querySelector("[data-detail]").textContent = `${stage.detail} · ${stage.ms}ms`;
    });
  }

  /* ---------------- 通知 ---------------- */
  function renderNotice(data) {
    const notice = $("#notice");
    const text = $("#noticeText");
    const meta = data.meta;
    let kind = "info";
    let body = "";
    if (meta.fallback) {
      kind = "warn";
      body = `<b>实时采集不可用，已自动降级。</b>${esc(meta.warnings.join("；"))}<br />演示数据源按关键词确定性生成，结果仅用于验证完整链路。`;
    } else if (meta.is_demo) {
      body = `<b>当前为示例数据。</b>演示数据源按「${esc(data.keyword)}」确定性生成三平台商品（含重复挂牌与引流价，用于演示清洗链路），同一关键词多次运行结果一致。切换上方数据源为「实时采集」可尝试真实抓取。`;
    } else {
      kind = "ok";
      body = `<b>实时采集成功。</b>本次价格已写入本地 SQLite 快照库，重复运行可逐步积累真实趋势。${
        meta.warnings.length ? `<br />${esc(meta.warnings.join("；"))}` : ""
      }`;
    }
    notice.className = `notice ${kind}`;
    text.innerHTML = body;
  }

  /* ---------------- KPI ---------------- */
  function renderKpis(data) {
    const stats = data.stats;
    const meta = data.meta;
    const cards = [
      ["有效报价", `${stats.count}`, `原始 ${meta.clean.raw} 条`, "≡"],
      ["覆盖型号", `${stats.group_count}`, `${stats.platform_count} 个平台 · ${meta.clean.duplicates} 条重复已合并`, "▦"],
      ["最低到手价", money(stats.min_price), `均价 ${money(stats.avg_price)}`, "¥"],
      ["最高价差", `${stats.max_spread_pct}%`, "同型号跨平台最大价差", "%"],
      ["总销量", salesText(stats.total_sales), `${stats.best_platform_name}最低价 ${stats.best_platform_wins} 次`, "↗"],
    ];
    $("#kpis").innerHTML = cards
      .map(
        ([label, value, hint, icon], index) => `
      <div class="kpi ${index === 2 ? "accent" : ""}">
        <div class="kpi-top"><span class="kpi-label">${label}</span><span class="kpi-ico">${icon}</span></div>
        <strong>${value}</strong>
        <div class="kpi-hint">${esc(hint)}</div>
      </div>`
      )
      .join("");
  }

  /* ---------------- 推荐 ---------------- */
  function renderRecommendations(data) {
    $("#recs").innerHTML = data.recommendations
      .map((rec, index) => {
        const item = rec.listing;
        const original = item.list_price
          ? `<span class="rec-origin">${money(item.list_price)}</span>`
          : "";
        return `
        <article class="rec" data-type="${rec.type}" data-sid="${item.platform}-${item.sku}" tabindex="0">
          <div class="rec-head">
            <span class="rec-label">${esc(rec.label)}</span>
            <span class="rec-idx">0${index + 1}</span>
          </div>
          <div class="rec-title">${esc(item.title)}</div>
          <div class="rec-price-row">
            <span class="rec-price"><small>¥</small>${num(item.price)}</span>${original}
          </div>
          <div class="rec-meta">
            <span class="plat-pill ${item.platform}"><i></i>${esc(item.platform_name)}</span>
            <span>${esc(truncate(item.shop, 12))}</span>
          </div>
          <div class="rec-meta">
            <span>销量 ${salesText(item.sales)}</span>
            <span>评分 ${item.shop_rating || "—"}</span>
            <span class="rec-score">性价比 <b>${item.value_score}</b></span>
          </div>
          <div class="rec-reason">${esc(rec.reason)}</div>
        </article>`;
      })
      .join("");

    $$(".rec").forEach((card) => {
      const open = () => flashRow(card.dataset.sid);
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
  }

  function flashRow(sid) {
    if (!state.payload) return;
    const white = $$(".segmented button[data-p]").find((btn) => btn.dataset.p === "");
    if (white) white.click();
    $("#filterInput").value = "";
    state.query = "";
    renderTable();
    const row = $(`#listingBody tr[data-sid="${sid}"]`);
    if (!row) {
      toast("该商品未在当前筛选结果中");
      return;
    }
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.classList.remove("flash");
    void row.offsetWidth;
    row.classList.add("flash");
  }

  /* ---------------- 横向对比 ---------------- */
  function renderComparison(data) {
    const groups = [...data.groups].sort((a, b) => {
      const multi = (b.platform_count > 1) - (a.platform_count > 1);
      return multi || b.spread_pct - a.spread_pct || a.min_price - b.min_price;
    });
    $("#comparison").innerHTML = groups
      .map((group) => {
        const map = Object.fromEntries(group.listings.map((item) => [item.platform, item]));
        const chips = ["jd", "tb", "pdd"]
          .map((key) => {
            const platform = PLATFORM[key];
            const item = map[key];
            if (!item) {
              return `<div class="pchip empty ${key}"><span class="pname"><i></i>${platform.name}</span><b>无货</b></div>`;
            }
            const low = Math.abs(item.price - group.min_price) < 0.005;
            return `
              <div class="pchip ${key} ${low ? "low" : ""}">
                ${low ? '<span class="lowtag">最低</span>' : ""}
                <span class="pname"><i></i>${platform.name}</span>
                <b>${money(item.price)}</b>
              </div>`;
          })
          .join("");
        return `
        <div class="cmp-row">
          <div>
            <div class="cmp-name">${esc(group.model_name)}</div>
            <div class="cmp-sub">
              <span>${group.platform_count > 1 ? `${group.platform_count} 个平台有货` : "仅单平台有货"}</span>
              <span>·</span><span>销量 ${salesText(group.total_sales)}</span>
              <span>·</span><span>${group.shop_count} 家店铺</span>
            </div>
          </div>
          <div class="cmp-prices">${chips}</div>
          <div class="cmp-spread">
            <b>${group.spread_pct}%</b><span>跨平台价差</span>
            <em>最多省 ${money(group.savings)}</em>
          </div>
        </div>`;
      })
      .join("");
  }

  /* ---------------- 平台胜出 ---------------- */
  function renderWins(data) {
    const wins = { jd: { wins: 0, save: 0 }, tb: { wins: 0, save: 0 }, pdd: { wins: 0, save: 0 } };
    const groups = data.groups.filter((group) => group.platform_count > 1);
    groups.forEach((group) => {
      const bucket = wins[group.best_platform];
      if (!bucket) return;
      bucket.wins += 1;
      bucket.save += ((group.max_price - group.min_price) / group.max_price) * 100;
    });
    const maxWins = Math.max(1, ...Object.values(wins).map((item) => item.wins));
    $("#platformWins").innerHTML =
      Object.entries(wins)
        .map(([key, value]) => {
          const platform = PLATFORM[key];
          const width = value.wins ? Math.max(6, (value.wins / maxWins) * 100) : 0;
          const save = value.wins ? (value.save / value.wins).toFixed(1) : "0.0";
          return `
          <div class="win-row">
            <div class="win-top">
              <span class="nm"><i style="background:${platform.color}"></i>${platform.name}</span>
              <span class="val">${value.wins} 次最低 · 平均省 ${save}%</span>
            </div>
            <div class="track"><i style="width:${width}%;background:${platform.color}"></i></div>
          </div>`;
        })
        .join("") +
      `<div class="win-note">基于 ${groups.length} 个多平台在售型号统计：该平台到手价为同型号最低的次数，以及相对该型号最高价平均可节省的比例。</div>`;
  }

  /* ---------------- 价格趋势 ---------------- */
  function renderTrend(data) {
    const trend = data.trend;
    const legend = $("#trendLegend");
    const holder = $("#trendChart");
    if (!trend || !trend.series || !trend.series.length) {
      legend.innerHTML = "";
      holder.innerHTML = '<div class="chart-empty">当前数据源暂无历史价格快照，趋势图将在多次采集后生成。</div>';
      $("#trendHint").textContent = "无历史数据";
      return;
    }
    $("#trendHint").textContent = trend.synthetic
      ? "近 30 天 · 演示数据源内置模拟序列 · 悬停查看每日价格"
      : "近 30 天 · 基于本地快照库 · 悬停查看每日价格";
    legend.innerHTML = trend.series
      .map((line) => `<span><i style="background:${line.color}"></i>${esc(truncate(line.name, 18))}</span>`)
      .join("");

    const W = 1000, H = 320;
    const pad = { l: 56, r: 24, t: 16, b: 32 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;
    const dates = trend.dates;
    const values = trend.series.flatMap((line) => line.prices);
    let low = Math.min(...values), high = Math.max(...values);
    const span = high - low || Math.max(high * 0.1, 1);
    low -= span * 0.12;
    high += span * 0.15;
    const range = high - low;
    const xAt = (i) => pad.l + (plotW * i) / Math.max(dates.length - 1, 1);
    const yAt = (value) => pad.t + plotH * (1 - (value - low) / range);

    let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="价格趋势">`;
    svg += `<defs>`;
    trend.series.forEach((line, index) => {
      svg += `<linearGradient id="area-${index}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${line.color}" stop-opacity="0.16"/>
        <stop offset="100%" stop-color="${line.color}" stop-opacity="0"/>
      </linearGradient>`;
    });
    svg += `</defs>`;
    for (let step = 0; step <= 4; step += 1) {
      const value = low + (range * step) / 4;
      const y = yAt(value);
      svg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${W - pad.r}" y2="${y.toFixed(1)}" stroke="#eef0f3" stroke-width="1"/>`;
      svg += `<text x="${pad.l - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="10.5" fill="#98a2b3">¥${Math.round(value).toLocaleString("zh-CN")}</text>`;
    }
    const tick = Math.max(1, Math.floor(dates.length / 6));
    dates.forEach((label, index) => {
      if (index % tick !== 0 && index !== dates.length - 1) return;
      svg += `<text x="${xAt(index).toFixed(1)}" y="${H - 10}" text-anchor="middle" font-size="10.5" fill="#98a2b3">${esc(label)}</text>`;
    });
    trend.series.forEach((line, index) => {
      const points = line.prices.map((price, i) => `${xAt(i).toFixed(1)},${yAt(price).toFixed(1)}`).join(" ");
      if (index === 0) {
        svg += `<polygon points="${pad.l},${pad.t + plotH} ${points} ${xAt(line.prices.length - 1)},${pad.t + plotH}" fill="url(#area-0)" opacity="0.9"/>`;
      }
      svg += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
      svg += `<circle cx="${xAt(line.prices.length - 1).toFixed(1)}" cy="${yAt(line.prices[line.prices.length - 1]).toFixed(1)}" r="3.4" fill="#fff" stroke="${line.color}" stroke-width="2.2"/>`;
    });
    svg += `<g id="trendHover"></g>`;
    svg += `<rect x="${pad.l}" y="${pad.t}" width="${plotW}" height="${plotH}" fill="transparent" data-hover="1"/>`;
    svg += `</svg>`;
    holder.innerHTML = svg;

    state.trendGeom = { W, H, pad, plotW, plotH, xAt, yAt, dates, series: trend.series };
    const svgEl = holder.querySelector("svg");
    svgEl.addEventListener("mousemove", (event) => handleTrendMove(event, svgEl));
    svgEl.addEventListener("mouseleave", () => {
      $("#trendTip").classList.remove("on");
      const hover = $("#trendHover");
      if (hover) hover.innerHTML = "";
    });
  }

  function handleTrendMove(event, svgEl) {
    const geom = state.trendGeom;
    if (!geom) return;
    const rect = svgEl.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / rect.width;
    const x = ratio * geom.W;
    const steps = Math.max(geom.dates.length - 1, 1);
    const index = Math.max(0, Math.min(steps, Math.round(((x - geom.pad.l) / geom.plotW) * steps)));
    const hover = $("#trendHover");
    let marks = `<line x1="${geom.xAt(index).toFixed(1)}" y1="${geom.pad.t}" x2="${geom.xAt(index).toFixed(1)}" y2="${geom.pad.t + geom.plotH}" stroke="#c9ccd3" stroke-width="1" stroke-dasharray="3 4"/>`;
    let rows = "";
    geom.series.forEach((line) => {
      const price = line.prices[index];
      if (price == null) return;
      marks += `<circle cx="${geom.xAt(index).toFixed(1)}" cy="${geom.yAt(price).toFixed(1)}" r="4" fill="#fff" stroke="${line.color}" stroke-width="2"/>`;
      rows += `<div class="row"><span><i style="background:${line.color}"></i>${esc(truncate(line.name, 16))}</span><b>${money(price)}</b></div>`;
    });
    hover.innerHTML = marks;
    const tip = $("#trendTip");
    tip.innerHTML = `<b>${esc(geom.dates[index])}</b>${rows}`;
    const wrapRect = $("#trendWrap").getBoundingClientRect();
    const px = rect.left - wrapRect.left + (geom.xAt(index) / geom.W) * rect.width;
    const topY = Math.min(...geom.series.map((line) => geom.yAt(line.prices[index] ?? line.prices[line.prices.length - 1])));
    const py = rect.top - wrapRect.top + (topY / geom.H) * rect.height;
    tip.style.left = `${px}px`;
    tip.style.top = `${py - 14}px`;
    tip.classList.add("on");
  }

  /* ---------------- 价格 × 销量气泡图 ---------------- */
  function renderBubble(data) {
    const listings = data.listings;
    if (!listings.length) {
      $("#bubbleChart").innerHTML = '<div class="chart-empty">暂无数据</div>';
      return;
    }
    const W = 1000, H = 340;
    const pad = { l: 58, r: 24, t: 22, b: 40 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;
    const prices = listings.map((item) => item.price);
    const minP = Math.min(...prices), maxP = Math.max(...prices);
    const spanP = maxP - minP || 1;
    const xMin = minP - spanP * 0.08, xMax = maxP + spanP * 0.08;
    const sales = listings.map((item) => Math.log10(item.sales + 10));
    const yMin = Math.min(...sales) - 0.15, yMax = Math.max(...sales) + 0.15;
    const xAt = (price) => pad.l + ((price - xMin) / (xMax - xMin)) * plotW;
    const yAt = (value) => pad.t + plotH * (1 - (value - yMin) / (yMax - yMin));
    const median = [...prices].sort((a, b) => a - b)[Math.floor(prices.length / 2)];

    let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="价格销量分布">`;
    for (let step = 0; step <= 4; step += 1) {
      const value = xMin + ((xMax - xMin) * step) / 4;
      const x = xAt(value);
      svg += `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t + plotH}" stroke="#f0f0ee" stroke-width="1"/>`;
      svg += `<text x="${x.toFixed(1)}" y="${H - 12}" text-anchor="middle" font-size="10.5" fill="#98a2b3">¥${Math.round(value).toLocaleString("zh-CN")}</text>`;
    }
    const yTicks = [2, 3, 4];
    yTicks.forEach((value) => {
      if (value < yMin || value > yMax) return;
      const y = yAt(value);
      svg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${W - pad.r}" y2="${y.toFixed(1)}" stroke="#f0f0ee" stroke-width="1"/>`;
      const label = value === 2 ? "100" : value === 3 ? "1,000" : "10,000";
      svg += `<text x="${pad.l - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="10.5" fill="#98a2b3">${label}</text>`;
    });
    svg += `<text x="${pad.l - 10}" y="${pad.t - 8}" font-size="10" fill="#b6bcc7">销量</text>`;
    svg += `<text x="${W - pad.r}" y="${H - 26}" text-anchor="end" font-size="10" fill="#b6bcc7">到手价 →</text>`;
    svg += `<line x1="${xAt(median).toFixed(1)}" y1="${pad.t}" x2="${xAt(median).toFixed(1)}" y2="${pad.t + plotH}" stroke="#c9ccd3" stroke-width="1" stroke-dasharray="4 5"/>`;
    svg += `<text x="${(xAt(median) + 6).toFixed(1)}" y="${pad.t + 10}" font-size="10" fill="#98a2b3">价格中位数 ${money(median)}</text>`;

    listings.forEach((item) => {
      const platform = PLATFORM[item.platform] || { color: "#64748b" };
      const radius = item.shop_rating ? Math.max(6, Math.min(13, (item.shop_rating - 4.3) * 20)) : 7;
      const cx = xAt(item.price), cy = yAt(Math.log10(item.sales + 10));
      svg += `<circle class="bubble" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${radius.toFixed(1)}"
        fill="${platform.color}" fill-opacity="0.55" stroke="${platform.color}" stroke-width="1.3"
        data-sid="${item.platform}-${item.sku}" data-price="${item.price}" data-sales="${item.sales}"
        data-title="${esc(item.title)}" data-platform="${esc(item.platform_name)}" data-value="${item.value_score}"
        style="cursor:pointer" />`;
    });
    svg += `</svg>`;
    $("#bubbleChart").innerHTML = svg;

    state.bubbleGeom = { W, H, pad, plotW, plotH, xAt, yAt };
    $$("#bubbleChart .bubble").forEach((node) => {
      node.addEventListener("mousemove", (event) => {
        const tip = $("#bubbleTip");
        tip.innerHTML = `<b>${esc(node.dataset.title)}</b>
          <div class="row"><span>${esc(node.dataset.platform)} · 性价比 ${node.dataset.value}</span></div>
          <div class="row"><span>到手价</span><b>${money(Number(node.dataset.price))}</b></div>
          <div class="row"><span>销量</span><b>${Number(node.dataset.sales).toLocaleString("zh-CN")}</b></div>`;
        const wrapRect = $("#bubbleWrap").getBoundingClientRect();
        tip.style.left = `${event.clientX - wrapRect.left}px`;
        tip.style.top = `${event.clientY - wrapRect.top - 18}px`;
        tip.classList.add("on");
      });
      node.addEventListener("mouseleave", () => $("#bubbleTip").classList.remove("on"));
      node.addEventListener("click", () => flashRow(node.dataset.sid));
    });
  }

  /* ---------------- 明细表 ---------------- */
  function tagClass(tag) {
    if (tag === "全网最低") return "hot";
    if (tag === "性价比之选") return "value";
    if (tag === "销量冠军" || tag === "热销之选") return "sales";
    if (tag === "口碑最佳" || tag === "口碑之选") return "rating";
    return "";
  }

  function sortedListings() {
    if (!state.payload) return [];
    let rows = [...state.payload.listings];
    if (state.platformFilter) rows = rows.filter((item) => item.platform === state.platformFilter);
    if (state.query) {
      const query = state.query.toLowerCase();
      rows = rows.filter(
        (item) =>
          item.title.toLowerCase().includes(query) || item.shop.toLowerCase().includes(query)
      );
    }
    const sorters = {
      price: (a, b) => a.price - b.price,
      sales: (a, b) => b.sales - a.sales,
      value: (a, b) => b.value_score - a.value_score,
      rating: (a, b) => (b.shop_rating || 0) - (a.shop_rating || 0),
    };
    return rows.sort(sorters[state.sort] || sorters.price);
  }

  function renderTable() {
    const rows = sortedListings();
    const total = state.payload ? state.payload.listings.length : 0;
    $("#listingBody").innerHTML = rows
      .map(
        (item) => `
      <tr data-sid="${item.platform}-${item.sku}">
        <td class="cell-rank">${item.rank}</td>
        <td><span class="plat-pill ${item.platform}"><i></i>${esc(item.platform_name)}</span></td>
        <td class="cell-name">
          <a href="${esc(item.url)}" target="_blank" rel="noreferrer" title="${esc(item.title)}">${esc(item.title)}</a>
          <div class="cell-sub">${esc(item.shop)} · 评分 ${item.shop_rating || "—"}${item.coupon ? ` · ${esc(item.coupon)}` : ""}</div>
        </td>
        <td class="cell-price">${money(item.price)}${
          item.list_price ? `<small>原价 ${money(item.list_price)}</small>` : ""
        }</td>
        <td class="mono">${salesText(item.sales)}</td>
        <td>
          <div class="score-cell">
            <div class="score-bar"><i style="width:${Math.max(4, Math.min(100, item.value_score))}%"></i></div>
            <span>${item.value_score}</span>
          </div>
        </td>
        <td>${item.tags.map((tag) => `<span class="tag ${tagClass(tag)}">${esc(tag)}</span>`).join("")}</td>
        <td><a class="link-out" href="${esc(item.url)}" target="_blank" rel="noreferrer" title="打开商品页">↗</a></td>
      </tr>`
      )
      .join("");
    $("#tableFoot").textContent = `显示 ${rows.length} / ${total} 条有效报价 · 已按${
      { price: "价格", sales: "销量", value: "性价比", rating: "评分" }[state.sort]
    }排序`;
    if (!rows.length) {
      $("#listingBody").innerHTML = `<tr><td colspan="8"><div class="empty-state">没有匹配的报价，试试调整筛选条件。</div></td></tr>`;
    }
  }

  /* ---------------- 主渲染 ---------------- */
  function render(data) {
    state.payload = data;
    if (!data.listings.length) {
      $("#emptyState").style.display = "";
      $("#emptyState").innerHTML = "<b>没有采集到有效商品</b>请更换关键词或调整平台后重试";
      return;
    }
    $("#emptyState").style.display = "none";
    $("#resultHead").style.display = "";
    $("#resultKeyword").textContent = data.keyword;
    const platformText = data.meta.platforms
      .map((item) => `${item.name} ${item.count}`)
      .join(" · ");
    $("#resultMeta").textContent = `${platformText} · 耗时 ${data.duration_ms}ms · ${data.generated_at} · ${data.meta.source_label}`;

    const reportLink = $("#reportLink");
    const csvLink = $("#csvLink");
    if (data.artifacts && data.artifacts.report) {
      reportLink.href = data.artifacts.report;
      reportLink.style.display = "";
      csvLink.href = data.artifacts.csv;
      csvLink.style.display = "";
    } else {
      reportLink.style.display = "none";
      csvLink.style.display = "none";
    }

    renderKpis(data);
    renderRecommendations(data);
    renderComparison(data);
    renderWins(data);
    renderTrend(data);
    renderBubble(data);
    state.platformFilter = "";
    state.query = "";
    state.sort = "price";
    $("#sortSelect").value = "price";
    $("#filterInput").value = "";
    $$("#platformFilter button").forEach((btn) => btn.classList.toggle("on", btn.dataset.p === ""));
    renderTable();

    ["recsSection", "compareSection", "winsSection", "trendSection", "bubbleSection", "tableSection"].forEach(
      (id) => {
        const el = document.getElementById(id);
        el.style.display = "";
      }
    );
    renderNotice(data);
  }

  /* ---------------- 请求 ---------------- */
  async function runSearch({ keyword, platforms, source, init = false }) {
    if (!platforms.length) {
      toast("请至少选择一个平台", true);
      return;
    }
    setLoading(true);
    setStatus(true);
    startPipeline();
    $("#notice").classList.add("hidden");
    const started = performance.now();
    try {
      const params = new URLSearchParams({
        keyword,
        platforms: platforms.join(","),
        source,
        limit: "60",
      });
      const response = await fetch(`/api/search?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "采集失败，请稍后重试");
      const elapsed = performance.now() - started;
      if (elapsed < 760) await new Promise((resolve) => setTimeout(resolve, 760 - elapsed));
      finishPipeline(data.meta.stages);
      render(data);
      setStatus(false, data);
      $("#notice").classList.remove("hidden");
      if (!init) toast(`采集完成：${data.stats.count} 条有效报价 / ${data.stats.group_count} 个型号`);
      const url = new URL(window.location.href);
      url.searchParams.set("keyword", keyword);
      url.searchParams.set("source", source);
      window.history.replaceState(null, "", url.toString());
    } catch (error) {
      clearInterval(pipelineTimer);
      const status = $("#sourceStatus");
      status.classList.remove("demo");
      status.classList.add("warn");
      status.innerHTML = "<i></i>采集失败";
      if (!state.payload) {
        $("#emptyState").style.display = "";
        $("#emptyState").innerHTML = `<b>采集失败</b>${esc(error.message)}`;
      }
      toast(error.message || "采集失败", true);
    } finally {
      setLoading(false);
    }
  }

  /* ---------------- 事件 ---------------- */
  function bind() {
    $("#searchForm").addEventListener("submit", (event) => {
      event.preventDefault();
      const keyword = $("#keywordInput").value.trim();
      if (!keyword) {
        toast("请输入搜索关键词", true);
        return;
      }
      const platforms = $$('#platformToggles input:checked').map((input) => input.value);
      runSearch({ keyword, platforms, source: $("#sourceSelect").value });
    });

    $$("#platformToggles .ptoggle").forEach((label) => {
      label.addEventListener("click", () => {
        setTimeout(() => label.classList.toggle("on", label.querySelector("input").checked), 0);
      });
    });

    $$(".quick button").forEach((button) => {
      button.addEventListener("click", () => {
        $("#keywordInput").value = button.dataset.kw;
        $("#searchForm").requestSubmit();
      });
    });

    $$("#platformFilter button").forEach((button) => {
      button.addEventListener("click", () => {
        state.platformFilter = button.dataset.p;
        $$("#platformFilter button").forEach((item) => item.classList.toggle("on", item === button));
        renderTable();
      });
    });

    $("#sortSelect").addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderTable();
    });

    $("#filterInput").addEventListener("input", (event) => {
      state.query = event.target.value.trim();
      renderTable();
    });
  }

  function init() {
    bind();
    const params = new URLSearchParams(window.location.search);
    const keyword = (params.get("keyword") || "机械键盘").trim() || "机械键盘";
    const requested = params.get("source");
    const source = ["auto", "live"].includes(requested) ? requested : "demo";
    $("#keywordInput").value = keyword;
    $("#sourceSelect").value = source;
    runSearch({
      keyword,
      platforms: ["jd", "tb", "pdd"],
      source,
      init: true,
    });
  }

  init();
})();
