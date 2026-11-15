"""领域模型：平台、商品条目、采集结果。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

PLATFORMS: dict[str, dict[str, str]] = {
    "jd": {"key": "jd", "name": "京东", "color": "#e1251b", "home": "https://www.jd.com"},
    "tb": {"key": "tb", "name": "淘宝", "color": "#f08200", "home": "https://www.taobao.com"},
    "pdd": {"key": "pdd", "name": "拼多多", "color": "#b5179e", "home": "https://www.pinduoduo.com"},
}
PLATFORM_KEYS: list[str] = list(PLATFORMS.keys())


def platform_name(key: str) -> str:
    return PLATFORMS.get(key, {}).get("name", key)


def platform_color(key: str) -> str:
    return PLATFORMS.get(key, {}).get("color", "#64748b")


@dataclass
class Listing:
    """一条商品挂牌信息（同一型号在不同平台/店铺各算一条）。"""

    platform: str
    title: str
    price: float
    sales: int = 0
    shop: str = ""
    shop_rating: float = 0.0
    url: str = ""
    sku: str = ""
    list_price: float | None = None
    coupon: str = ""
    model_key: str = ""
    model_name: str = ""
    fetched_at: str = ""
    source: str = "demo"
    is_demo: bool = False

    # 以下字段由分析层写入
    value_score: float = 0.0
    price_score: float = 0.0
    sales_score: float = 0.0
    rating_score: float = 0.0
    tags: list[str] = field(default_factory=list)
    rank: int = 0

    # ---- 派生属性 ----
    @property
    def platform_name(self) -> str:
        return platform_name(self.platform)

    @property
    def platform_color(self) -> str:
        return platform_color(self.platform)

    @property
    def discount(self) -> float | None:
        if not self.list_price or self.list_price <= self.price:
            return None
        return round((1 - self.price / self.list_price) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            platform_name=self.platform_name,
            platform_color=self.platform_color,
            discount=self.discount,
        )
        return data


@dataclass
class SourceResult:
    listings: list[Listing]
    requested_source: str = "demo"
    source_label: str = "演示数据源"
    is_demo: bool = True
    fallback: bool = False
    warnings: list[str] = field(default_factory=list)
    platform_counts: dict[str, int] = field(default_factory=dict)
    # 演示数据源会附带 30 天价格序列；真实采集依赖本地快照库
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


@dataclass
class SearchResult:
    keyword: str
    generated_at: str
    duration_ms: int
    meta: dict[str, Any]
    stats: dict[str, Any]
    recommendations: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    listings: list[Listing]
    trend: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        by_sku = {(item.platform, item.sku): item for item in self.listings}
        recommendations = []
        for rec in self.recommendations:
            row = rec["listing"]
            fresh = by_sku.get((row.get("platform"), row.get("sku")))
            recommendations.append({**rec, "listing": fresh.to_dict() if fresh else row})
        groups = []
        for group in self.groups:
            data = {key: value for key, value in group.items() if key != "listings"}
            data["listings"] = [item.to_dict() for item in group["listings"]]
            data["avg_rating"] = group.get("avg_rating", 0)
            groups.append(data)
        return {
            "keyword": self.keyword,
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
            "stats": self.stats,
            "recommendations": recommendations,
            "groups": groups,
            "listings": [item.to_dict() for item in self.listings],
            "trend": self.trend,
        }


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fmt_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"¥{value:,.2f}"
