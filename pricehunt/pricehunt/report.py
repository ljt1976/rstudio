"""HTML 报告生成：自包含（无外链、无 JS 依赖），可直接分享或打印。"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import PLATFORMS, PLATFORM_KEYS

PLATFORM_ORDER = PLATFORM_KEYS

CSS = """
:root{
  --ink:#101828; --muted:#667085; --line:#e6e8ee; --bg:#f4f5f7; --card:#ffffff;
  --accent:#ff5a36; --accent-soft:#fff1ec; --blue:#2563eb; --green:#079455;
  --jd:#e1251b; --tb:#f08200; --pdd:#b5179e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",Inter,system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;line-height:1.6}
.wrap{max-width:1160px;margin:0 auto;padding:0 28px 64px}
.hero{background:linear-gradient(135deg,#111726 0%,#1c2438 60%,#252f47 100%);color:#fff;padding:44px 0 38px;margin-bottom:28px}
.hero .wrap{padding-bottom:0}
.brand{display:flex;align-items:center;gap:10px;font-size:13px;letter-spacing:.18em;color:#9aa6bf;text-transform:uppercase}
.brand .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 16px var(--accent)}
h1{font-size:34px;margin:14px 0 6px;letter-spacing:-.02em;font-weight:700}
h1 .kw{color:#ffb199}
.sub{color:#b6c0d4;font-size:14px;margin:0}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.chip{font-size:12px;padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);color:#d7deeb}
.chip.warn{background:rgba(255,90,54,.14);border-color:rgba(255,90,54,.35);color:#ffb199}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
h2{font-size:19px;margin:0 0 4px;letter-spacing:-.01em}
.sec{margin-top:30px}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin-bottom:14px}
.sec-head p{margin:0;color:var(--muted);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.kpi span{display:block;font-size:12px;color:var(--muted)}
.kpi strong{display:block;font-size:24px;letter-spacing:-.02em;margin-top:4px;font-weight:700}
.kpi em{font-style:normal;font-size:12px;color:var(--muted)}
.recs{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.rec{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;position:relative;overflow:hidden;display:flex;flex-direction:column;gap:8px}
.rec::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:var(--accent)}
.rec .tag{font-size:12px;font-weight:700;color:var(--accent);letter-spacing:.04em}
.rec .name{font-size:13px;font-weight:600;line-height:1.45;min-height:38px}
.rec .price{font-size:22px;font-weight:700;letter-spacing:-.02em}
.rec .meta{font-size:12px;color:var(--muted);display:flex;gap:8px;flex-wrap:wrap}
.rec .reason{font-size:12px;color:var(--muted);border-top:1px dashed var(--line);padding-top:8px;margin-top:auto}
.pill{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:2px 7px;border-radius:999px;background:#f2f4f7;color:#475467}
.pill.jd{background:#fdecea;color:var(--jd)}
.pill.tb{background:#fff3e0;color:#c76a00}
.pill.pdd{background:#fbe9f6;color:var(--pdd)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:760px}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);background:#fafbfc;white-space:nowrap}
tr:last-child td{border-bottom:none}
td.num{font-variant-numeric:tabular-nums}
.price-cell{display:flex;align-items:center;gap:6px;white-space:nowrap}
.price-cell b{font-variant-numeric:tabular-nums}
.price-cell.low b{color:var(--accent)}
.mini{font-size:10px;padding:1px 6px;border-radius:4px;background:var(--accent-soft);color:var(--accent);font-weight:700}
.spread{font-variant-numeric:tabular-nums;color:var(--muted)}
.bar-cell{display:flex;align-items:center;gap:10px}
.bar{height:7px;border-radius:999px;background:linear-gradient(90deg,#2563eb,#7c9cf5);min-width:4px}
.bar.price{background:linear-gradient(90deg,#ff5a36,#ff9d80)}
.chart-card{padding:18px 20px 10px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin:0 0 6px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
svg{display:block;width:100%;height:auto}
.split{display:grid;grid-template-columns:1.45fr 1fr;gap:14px;align-items:start}
.value-list{display:grid;grid-template-columns:1fr 1fr;gap:14px 34px}
.value-row{display:grid;grid-template-columns:1fr 58px;gap:6px;font-size:12px}
.value-row .nm{display:flex;justify-content:space-between;gap:8px;color:#344054;margin-bottom:4px}
.value-row .nm span:last-child{color:var(--muted);font-variant-numeric:tabular-nums}
.track{height:6px;background:#eef1f6;border-radius:999px;overflow:hidden}
.fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#079455,#3ccb8a)}
.note{font-size:12px;color:var(--muted);margin-top:10px}
.empty{padding:34px;text-align:center;color:var(--muted);font-size:13px}
.footer{margin-top:34px;border-top:1px solid var(--line);padding-top:18px;color:var(--muted);font-size:12px;line-height:1.8}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
.data-src{margin-top:8px}
@media (max-width:980px){.kpis{grid-template-columns:repeat(3,1fr)}.recs{grid-template-columns:repeat(2,1fr)}.split{grid-template-columns:1fr}}
@media (max-width:760px){.value-list{grid-template-columns:1fr}}
@media (max-width:600px){h1{font-size:26px}.kpis{grid-template-columns:repeat(2,1fr)}.recs{grid-template-columns:1fr}}
@media print{body{background:#fff}.hero{background:#fff;color:#000}.hero .sub,.brand{color:#555}.card{box-shadow:none}}
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def money(value: float | None) -> str:
    return "-" if value is None else f"¥{value:,.2f}"


def sales_text(value: int) -> str:
    if value >= 10000:
        return f"{value / 10000:.1f} 万"
    return str(value)


def _platform_pill(key: str) -> str:
    name = PLATFORMS.get(key, {}).get("name", key)
    return f'<span class="pill {key}">{esc(name)}</span>'


def svg_trend(trend: dict[str, Any], width: int = 980, height: int = 320) -> str:
    dates: list[str] = trend.get("dates") or []
    series: list[dict[str, Any]] = trend.get("series") or []
    if not dates or not series:
        return '<div class="empty">当前数据源暂无历史快照，趋势图将在多次采集后生成。</div>'

    left, right, top, bottom = 56, 18, 16, 34
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [price for line in series for price in line["prices"]]
    low, high = min(values), max(values)
    span = (high - low) or max(high * 0.08, 1)
    low -= span * 0.12
    high += span * 0.12
    span = high - low

    def x_at(index: int) -> float:
        return left + (plot_w * index / max(len(dates) - 1, 1))

    def y_at(price: float) -> float:
        return top + plot_h * (1 - (price - low) / span)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="价格走势图">']
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>'
    )
    for step in range(5):
        value = low + span * step / 4
        y = y_at(value)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" stroke="#eef0f4" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#98a2b3">¥{value:,.0f}</text>'
        )
    step = max(len(dates) // 6, 1)
    for index in range(0, len(dates), step):
        parts.append(
            f'<text x="{x_at(index):.1f}" y="{height - 12}" text-anchor="middle" font-size="11" fill="#98a2b3">{esc(dates[index])}</text>'
        )

    for line in series:
        prices = line["prices"]
        points = " ".join(f"{x_at(i):.1f},{y_at(p):.1f}" for i, p in enumerate(prices))
        color = line["color"]
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.4" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        parts.append(
            f'<circle cx="{x_at(len(prices) - 1):.1f}" cy="{y_at(prices[-1]):.1f}" r="3.6" fill="#fff" stroke="{color}" stroke-width="2.4"/>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{line["color"]}"></i>{esc(line["name"])}</span>'
        for line in series
    )
    note = esc(trend.get("note", ""))
    return (
        f'<div class="legend">{legend}</div>{"".join(parts)}'
        f'<div class="note">{note}</div>'
    )


def _recommendation_cards(recommendations: list[dict[str, Any]]) -> str:
    cards = []
    for rec in recommendations:
        item = rec["listing"]
        cards.append(
            f"""
            <article class="rec">
              <div class="tag">{esc(rec['label'])}</div>
              <div class="name">{esc(item['title'])}</div>
              <div class="price">{money(item['price'])}</div>
              <div class="meta">{_platform_pill(item['platform'])}<span>{esc(item['shop'])}</span></div>
              <div class="meta"><span>销量 {sales_text(item['sales'])}</span><span>评分 {item['shop_rating'] or '—'}</span><span>性价比 {item['value_score']}</span></div>
              <div class="reason">{esc(rec['reason'])}</div>
            </article>"""
        )
    return "".join(cards)


def _compare_rows(groups: list[dict[str, Any]]) -> str:
    rows = []
    for group in groups:
        by_platform = {item["platform"]: item for item in group["listings"]}
        cells = []
        cheapest = group["min_price"]
        for key in PLATFORM_ORDER:
            item = by_platform.get(key)
            if not item:
                cells.append('<td class="num" style="color:#c3c8d2">—</td>')
                continue
            is_low = abs(item["price"] - cheapest) < 0.005
            badge = '<span class="mini">最低</span>' if is_low else ""
            cells.append(
                f'<td><div class="price-cell {"low" if is_low else ""}"><b>{money(item["price"])}</b>{badge}</div>'
                f'<div style="font-size:11px;color:#98a2b3">{esc(item["shop"])}</div></td>'
            )
        note = (
            f'{group["platform_count"]} 个平台有货'
            if group["platform_count"] > 1
            else "仅单平台有货"
        )
        rows.append(
            f"""
            <tr>
              <td><strong>{esc(group['model_name'])}</strong>
                  <div style="font-size:11px;color:#98a2b3">{note} · {group['shop_count']} 家店铺</div></td>
              {''.join(cells)}
              <td class="spread">{group['spread_pct']}%<div style="font-size:11px;color:#98a2b3">省 {money(group['savings'])}</div></td>
              <td class="num">{sales_text(group['total_sales'])}</td>
            </tr>"""
        )
    return "".join(rows)


def _detail_rows(listings: list[dict[str, Any]], max_value: float) -> str:
    rows = []
    for item in listings:
        width = max(4, round(item["value_score"] / max(max_value, 1) * 100))
        tags = "".join(f'<span class="mini">{esc(tag)}</span>' for tag in item["tags"])
        rows.append(
            f"""
            <tr>
              <td class="num">{item['rank']}</td>
              <td>{_platform_pill(item['platform'])}</td>
              <td><a href="{esc(item['url'])}" target="_blank" rel="noreferrer">{esc(item['title'])}</a>
                  <div style="font-size:11px;color:#98a2b3">{esc(item['shop'])} · 店铺评分 {item['shop_rating'] or '—'}</div></td>
              <td class="num"><b>{money(item['price'])}</b>
                  {f'<div style="font-size:11px;color:#98a2b3">原价 {money(item["list_price"])}</div>' if item.get("list_price") else ''}</td>
              <td class="num">{sales_text(item['sales'])}</td>
              <td><div class="bar-cell"><div class="bar" style="width:{width}px"></div><span>{item['value_score']}</span></div>
                  <div>{tags}</div></td>
            </tr>"""
        )
    return "".join(rows)


def _value_bars(listings: list[dict[str, Any]]) -> str:
    top = sorted(listings, key=lambda x: -x["value_score"])[:8]
    max_score = max((item["value_score"] for item in top), default=1)
    rows = []
    for item in top:
        width = max(4, round(item["value_score"] / max_score * 100))
        rows.append(
            f"""
            <div class="value-row">
              <div>
                <div class="nm"><span>{esc(item['title'][:26])}</span><span>{item['value_score']}</span></div>
                <div class="track"><div class="fill" style="width:{width}%"></div></div>
              </div>
              <div style="text-align:right;font-weight:600;font-variant-numeric:tabular-nums">{money(item['price'])}</div>
            </div>"""
        )
    return "".join(rows)


def render_report(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    stats = payload["stats"]
    listings = payload["listings"]
    groups = payload["groups"]
    keywords = payload["keyword"]
    platform_chips = "".join(
        f'<span class="chip">{esc(p["name"])} · {p["count"]} 条</span>'
        for p in meta["platforms"]
    )
    warning_chips = "".join(
        f'<span class="chip warn">{esc(text)}</span>' for text in meta.get("warnings", [])
    )
    max_value = max((item["value_score"] for item in listings), default=1)
    stats_cards = [
        ("有效报价", f"{stats['count']} 条", f"原始 {meta['clean']['raw']} 条"),
        ("覆盖型号", f"{stats['group_count']}", f"{stats['platform_count']} 个平台"),
        ("最低到手价", money(stats["min_price"]), f"均价 {money(stats['avg_price'])}"),
        ("最高价差", f"{stats['max_spread_pct']}%", "跨平台同款价差"),
        ("总销量", sales_text(stats["total_sales"]), f"{stats['best_platform_name']}最低价次数最多"),
    ]
    kpis = "".join(
        f'<div class="kpi"><span>{label}</span><strong>{value}</strong><em>{hint}</em></div>'
        for label, value, hint in stats_cards
    )
    clean = meta["clean"]
    flow = (
        f"原始 {clean['raw']} → 去重 {clean['duplicates']} → 剔除异常 {clean['outliers']} → "
        f"有效 {clean['kept']}（{clean['merged_groups']} 个型号）"
    )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{esc(keywords)} · 商品价格采集对比报告</title>
<style>{CSS}</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div class="brand"><span class="dot"></span>PriceHunt · 价格采集与对比报告</div>
    <h1>「<span class="kw">{esc(keywords)}</span>」全网比价</h1>
    <p class="sub">采集时间 {esc(payload['generated_at'])} · 耗时 {payload['duration_ms']} ms · {esc(meta['source_label'])}</p>
    <div class="chips">{platform_chips}{warning_chips}<span class="chip">数据流：{esc(flow)}</span></div>
  </div>
</header>

<main class="wrap">
  <section class="kpis">{kpis}</section>

  <section class="sec">
    <div class="sec-head"><h2>性价比推荐</h2><p>四个推荐位分别对应不同商品，避免同款包揽</p></div>
    <div class="recs">{_recommendation_cards(payload['recommendations'])}</div>
  </section>

  <section class="sec">
    <div class="sec-head"><h2>商品横向对比</h2><p>按型号对齐三个平台的到手价，价差越大越值得比价</p></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>型号</th><th>京东</th><th>淘宝</th><th>拼多多</th><th>价差</th><th>销量</th></tr></thead>
        <tbody>{_compare_rows(groups)}</tbody>
      </table>
    </div>
  </section>

  <section class="sec">
    <div class="card chart-card">
      <div class="sec-head"><h2>价格趋势</h2><p>近 30 天价格走势</p></div>
      {svg_trend(payload['trend'])}
    </div>
  </section>

  <section class="sec">
    <div class="card">
      <div class="sec-head"><h2>性价比指数 TOP 8</h2><p>价格 45% / 销量 35% / 评分 20%</p></div>
      <div class="value-list">{_value_bars(listings)}</div>
    </div>
  </section>

  <section class="sec">
    <div class="sec-head"><h2>全部有效报价</h2><p>已按价格从低到高排序 · 点击商品名跳转原站</p></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>平台</th><th>商品 / 店铺</th><th>到手价</th><th>销量</th><th>性价比</th></tr></thead>
        <tbody>{_detail_rows(listings, max_value)}</tbody>
      </table>
    </div>
  </section>

  <footer class="footer">
    <div><strong>方法说明</strong>：清洗阶段对标题做全角转半角、促销词剥离与同店相似标题去重；按型号跨平台归组后，
    剔除同型号内价格低于中位数 45% 或高于 280% 的异常挂牌；性价比指数 = 价格 45% + 销量 35% + 店铺评分 20%，各维度归一化后加权。</div>
    <div class="data-src">数据来源：{esc(meta['source_label'])}。当前环境受平台风控限制，实时采集需配置对应平台 Cookie；演示数据源为确定性模拟数据，仅用于验证功能链路。</div>
    <div>报告生成于 {generated} · PriceHunt v1.0</div>
  </footer>
</main>
</body>
</html>"""


def write_report(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(payload), encoding="utf-8")
    return target
