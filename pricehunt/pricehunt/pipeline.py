"""流水线编排：采集 -> 清洗 -> 归组 -> 评分 -> 推荐 -> 趋势。"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .analysis import (
    build_groups,
    build_recommendations,
    build_stats,
    build_trend,
    score_listings,
    tag_listings,
)
from .cleaning import CleanStats, clean_listings
from .models import PLATFORMS, PLATFORM_KEYS, SearchResult, SourceResult, now_str
from .report import write_report
from .sources import SourceError, collect
from .storage import SnapshotStore, write_csv


@dataclass
class RunOutput:
    result: SearchResult
    clean_stats: CleanStats
    source_result: SourceResult
    raw_count: int


def run_search(
    keyword: str,
    platforms: list[str] | None = None,
    source: str = "demo",
    limit: int = 40,
    use_store: bool = True,
) -> RunOutput:
    keyword = keyword.strip()
    if not keyword:
        raise SourceError("请输入搜索关键词")

    started = time.perf_counter()
    source_result = collect(keyword, platforms, source=source, limit=limit)
    t_fetch = time.perf_counter()

    cleaned, clean_stats = clean_listings(source_result.listings)
    t_clean = time.perf_counter()

    score_listings(cleaned)
    groups = build_groups(cleaned)
    recommendations = build_recommendations(cleaned)
    tag_listings(cleaned, groups, recommendations)
    stats = build_stats(cleaned, groups)
    t_analyze = time.perf_counter()

    store = SnapshotStore() if use_store else None
    if store is not None and not source_result.is_demo:
        history = {
            group["model_key"]: store.history(keyword, group["model_key"]) for group in groups
        }
    else:
        history = source_result.history
    trend = build_trend(groups, history, source_result.is_demo)

    fetched_at = now_str()
    for item in cleaned:
        item.fetched_at = fetched_at
    if store is not None and not source_result.is_demo:
        store.record(keyword, cleaned, fetched_at)
    t_store = time.perf_counter()

    platform_counts: dict[str, int] = {key: 0 for key in PLATFORM_KEYS}
    for item in cleaned:
        platform_counts[item.platform] = platform_counts.get(item.platform, 0) + 1
    active = [p for p in PLATFORM_KEYS if platform_counts.get(p) or p in (platforms or [])]

    stages = [
        {
            "key": "fetch",
            "name": "多平台采集",
            "ms": round((t_fetch - started) * 1000),
            "detail": f"{len(source_result.listings)} 条原始挂牌 · {len(active)} 个平台",
        },
        {
            "key": "clean",
            "name": "清洗去重",
            "ms": round((t_clean - t_fetch) * 1000),
            "detail": f"去重 {clean_stats.duplicates} · 异常价 {clean_stats.outliers} · 无效 {clean_stats.invalid}",
        },
        {
            "key": "group",
            "name": "跨平台归组",
            "ms": round((t_analyze - t_clean) * 1000),
            "detail": f"{clean_stats.merged_groups} 个型号 · {clean_stats.kept} 条有效报价",
        },
        {
            "key": "insight",
            "name": "评分与趋势",
            "ms": round((t_store - t_analyze) * 1000),
            "detail": "性价比指数 · 30 天价格走势 · 推荐标注",
        },
    ]

    meta: dict[str, Any] = {
        "keyword": keyword,
        "platforms": [
            {
                "key": key,
                "name": PLATFORMS[key]["name"],
                "color": PLATFORMS[key]["color"],
                "count": platform_counts.get(key, 0),
            }
            for key in active
        ],
        "platform_counts": platform_counts,
        "source": source,
        "source_label": source_result.source_label,
        "is_demo": source_result.is_demo,
        "fallback": source_result.fallback,
        "warnings": source_result.warnings,
        "clean": clean_stats.to_dict(),
        "stages": stages,
        "fetched_at": fetched_at,
        "limit": limit,
        "snapshot_saved": bool(store is not None and not source_result.is_demo),
        "scoring": {
            "formula": "性价比指数 = 价格 45% + 销量 35% + 店铺评分 20%",
            "weights": {"price": 0.45, "sales": 0.35, "rating": 0.20},
        },
    }

    result = SearchResult(
        keyword=keyword,
        generated_at=fetched_at,
        duration_ms=round((time.perf_counter() - started) * 1000),
        meta=meta,
        stats=stats,
        recommendations=recommendations,
        groups=groups,
        listings=cleaned,
        trend=trend,
    )
    return RunOutput(
        result=result,
        clean_stats=clean_stats,
        source_result=source_result,
        raw_count=len(source_result.listings),
    )


def save_artifacts(out: RunOutput, out_dir: str | Path = "out/sessions") -> dict[str, Path]:
    """把一次采集落盘为 CSV + 自包含 HTML 报告。"""
    digest = hashlib.sha1(out.result.keyword.encode("utf-8")).hexdigest()[:10]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path(out_dir) / f"pricehunt-{digest}-{stamp}"
    csv_path = write_csv(out.result.listings, base.with_suffix(".csv"))
    html_path = write_report(out.result.to_dict(), base.with_suffix(".html"))
    return {"csv": csv_path, "html": html_path}
