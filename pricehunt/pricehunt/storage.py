"""持久化：价格快照 SQLite（支撑真实数据的趋势）+ CSV 导出。"""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .models import Listing

DEFAULT_DB = Path(__file__).resolve().parent.parent / "out" / "snapshots.db"


@dataclass
class SnapshotStore:
    path: Path = DEFAULT_DB

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    model_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    price REAL NOT NULL,
                    captured_on TEXT NOT NULL,
                    captured_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshot ON price_snapshot(keyword, model_key, captured_on)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def record(self, keyword: str, listings: list[Listing], captured_at: str) -> None:
        today = date.today().isoformat()
        rows = [
            (keyword, item.model_key, item.platform, item.price, today, captured_at)
            for item in listings
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO price_snapshot(keyword, model_key, platform, price, captured_on, captured_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def history(self, keyword: str, model_key: str, days: int = 30) -> list[dict[str, Any]]:
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT captured_on, MIN(price)
                FROM price_snapshot
                WHERE keyword = ? AND model_key = ? AND captured_on >= ?
                GROUP BY captured_on
                ORDER BY captured_on
                """,
                (keyword, model_key, since),
            ).fetchall()
        return [{"date": row[0][5:], "price": round(row[1], 2)} for row in rows]


def write_csv(listings: list[Listing], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "排名",
                "平台",
                "商品名称",
                "到手价",
                "原价",
                "销量",
                "店铺",
                "店铺评分",
                "优惠信息",
                "性价比指数",
                "最低价标签",
                "购买链接",
                "采集时间",
            ]
        )
        for item in listings:
            writer.writerow(
                [
                    item.rank,
                    item.platform_name,
                    item.title,
                    f"{item.price:.2f}",
                    f"{item.list_price:.2f}" if item.list_price else "",
                    item.sales,
                    item.shop,
                    item.shop_rating or "",
                    item.coupon,
                    item.value_score,
                    " / ".join(item.tags),
                    item.url,
                    item.fetched_at,
                ]
            )
    return target
