"""分析层：性价比评分、横向对比分组、推荐结论、价格趋势。"""
from __future__ import annotations

import math
import statistics
from typing import Any

from .models import Listing, platform_name

TREND_COLORS = ["#2563eb", "#e1251b", "#f08200", "#b5179e"]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def score_listings(listings: list[Listing]) -> None:
    """性价比指数 = 价格 45% + 销量 35% + 店铺评分 20%（各维度归一化到 0-100）。"""
    if not listings:
        return
    prices = [item.price for item in listings]
    min_price, max_price = min(prices), max(prices)
    logs = [math.log1p(item.sales) for item in listings]
    min_log, max_log = min(logs), max(logs)

    for item, log_sales in zip(listings, logs):
        if max_price > min_price:
            item.price_score = round((max_price - item.price) / (max_price - min_price) * 100, 1)
        else:
            item.price_score = 100.0
        if max_log > min_log:
            item.sales_score = round((log_sales - min_log) / (max_log - min_log) * 100, 1)
        else:
            item.sales_score = 60.0
        # 评分缺失（真实采集常见）时给中性分，避免拉低排序
        item.rating_score = (
            round(_clamp((item.shop_rating - 4.0) / 1.0 * 100), 1)
            if item.shop_rating > 0
            else 60.0
        )
        item.value_score = round(
            item.price_score * 0.45 + item.sales_score * 0.35 + item.rating_score * 0.20, 1
        )


def build_groups(listings: list[Listing]) -> list[dict[str, Any]]:
    buckets: dict[str, list[Listing]] = {}
    for item in listings:
        buckets.setdefault(item.model_key, []).append(item)

    groups: list[dict[str, Any]] = []
    for key, items in buckets.items():
        items.sort(key=lambda x: x.price)
        prices = [item.price for item in items]
        min_item = items[0]
        shops = {item.shop for item in items}
        groups.append(
            {
                "model_key": key,
                "model_name": min_item.model_name or min_item.title,
                "listings": items,
                "min_price": round(min(prices), 2),
                "max_price": round(max(prices), 2),
                "spread_pct": round((max(prices) - min(prices)) / min(prices) * 100, 1)
                if min(prices)
                else 0.0,
                "savings": round(max(prices) - min(prices), 2),
                "total_sales": sum(item.sales for item in items),
                "avg_rating": round(
                    statistics.mean([i.shop_rating for i in items if i.shop_rating > 0] or [0]), 2
                ),
                "best_platform": min_item.platform,
                "platform_count": len({item.platform for item in items}),
                "shop_count": len(shops),
            }
        )

    groups.sort(key=lambda g: (-g["platform_count"], g["min_price"]))
    return groups


def tag_listings(
    listings: list[Listing],
    groups: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> None:
    """表格标签与推荐卡保持一致，避免「推荐说热销、表格写销量冠军」的错位。"""
    for item in listings:
        item.tags = []
    by_sku = {(item.platform, item.sku): item for item in listings}
    for rec in recommendations:
        picked = by_sku.get((rec["listing"]["platform"], rec["listing"]["sku"]))
        if picked is None:
            continue
        label = "全网最低" if rec["type"] == "lowest" else rec["label"]
        if label not in picked.tags:
            picked.tags.append(label)
    for group in groups:
        if group["platform_count"] > 1:
            cheapest = group["listings"][0]
            if "全平台最低" not in cheapest.tags:
                cheapest.tags.append("全平台最低")
    for index, item in enumerate(sorted(listings, key=lambda x: x.price)):
        item.rank = index + 1


def build_recommendations(listings: list[Listing]) -> list[dict[str, Any]]:
    """四个推荐位尽量落到不同商品，避免同一款包揽所有标签。"""
    if not listings:
        return []
    top_lowest = min(listings, key=lambda x: (x.price, -x.value_score))
    top_value = max(listings, key=lambda x: (x.value_score, x.sales))
    top_sales = max(listings, key=lambda x: (x.sales, x.value_score))
    top_rating = max(listings, key=lambda x: (x.shop_rating, x.sales))

    used: set[int] = set()
    used_models: set[str] = set()
    specs = [
        ("lowest", "全网最低价", "当前所有平台中到手价最低，适合价格敏感型用户", "低价之选", lambda x: -x.price),
        ("value", "性价比之选", "综合价格、销量与店铺评分，性价比指数最高", "均衡之选", lambda x: x.value_score),
        ("sales", "销量冠军", "同批商品中销量最高，市场验证充分", "热销之选", lambda x: x.sales),
        ("rating", "口碑最佳", "店铺评分最高，售后与履约更有保障", "口碑之选", lambda x: (x.shop_rating, x.sales)),
    ]
    absolute = {"lowest": top_lowest, "value": top_value, "sales": top_sales, "rating": top_rating}

    result = []
    for kind, label, reason, alt_label, metric in specs:
        candidate = absolute[kind]
        if id(candidate) in used or candidate.model_key in used_models:
            candidate = None
        if candidate is None:
            pool = [
                x for x in listings if id(x) not in used and x.model_key not in used_models
            ]
            if not pool:
                pool = [x for x in listings if id(x) not in used]
            candidate = max(pool, key=metric) if pool else absolute[kind]
            label = alt_label
            reason = "在未入选型号中综合表现最优，可作为差异化备选"
        used.add(id(candidate))
        used_models.add(candidate.model_key)
        result.append(
            {"type": kind, "label": label, "reason": reason, "listing": candidate.to_dict()}
        )
    return result


def build_stats(listings: list[Listing], groups: list[dict[str, Any]]) -> dict[str, Any]:
    if not listings:
        return {}
    prices = sorted(item.price for item in listings)
    wins: dict[str, int] = {}
    for group in groups:
        if group["platform_count"] > 1:
            wins[group["best_platform"]] = wins.get(group["best_platform"], 0) + 1
    best_platform = max(wins, key=wins.get) if wins else listings[0].platform
    return {
        "count": len(listings),
        "group_count": len(groups),
        "platform_count": len({item.platform for item in listings}),
        "min_price": round(prices[0], 2),
        "max_price": round(prices[-1], 2),
        "avg_price": round(statistics.mean(prices), 2),
        "median_price": round(statistics.median(prices), 2),
        "total_sales": sum(item.sales for item in listings),
        "max_spread_pct": max((g["spread_pct"] for g in groups), default=0.0),
        "best_platform": best_platform,
        "best_platform_name": platform_name(best_platform),
        "best_platform_wins": wins.get(best_platform, 0),
    }


def build_trend(
    groups: list[dict[str, Any]],
    history: dict[str, list[dict[str, Any]]],
    is_demo: bool,
) -> dict[str, Any]:
    candidates = [group for group in groups if history.get(group["model_key"])]
    candidates.sort(key=lambda g: (-g["platform_count"], -g["total_sales"]))
    chosen = candidates[:4]
    if not chosen:
        return {"dates": [], "series": [], "synthetic": is_demo, "note": "暂无可绘制的历史价格"}

    dates = [point["date"] for point in history[chosen[0]["model_key"]]]
    series = []
    for index, group in enumerate(chosen):
        points = history[group["model_key"]]
        series.append(
            {
                "key": group["model_key"],
                "name": group["model_name"],
                "color": TREND_COLORS[index % len(TREND_COLORS)],
                "prices": [point["price"] for point in points],
                "min_price": group["min_price"],
            }
        )
    return {
        "dates": dates,
        "series": series,
        "synthetic": is_demo,
        "note": "演示数据源内置 30 天模拟价格序列" if is_demo else "基于本地快照库的真实采集历史",
    }
