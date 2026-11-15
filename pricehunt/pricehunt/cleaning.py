"""数据清洗：标准化 -> 校验 -> 同店去重 -> 型号归组 -> 异常价格剔除。"""
from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Listing

PROMO_WORDS = (
    "包邮",
    "秒杀",
    "官方正品",
    "全国联保",
    "顺丰",
    "百亿补贴",
    "限时立减",
    "限时",
    "正品",
    "旗舰店",
    "自营",
    "官方",
    "引流款",
    "券",
)

BRACKET_RE = re.compile(r"[【\[（(]([^】\]）)]*)[】\]）)]")
SPACE_RE = re.compile(r"\s+")


@dataclass
class CleanStats:
    raw: int = 0
    invalid: int = 0
    duplicates: int = 0
    outliers: int = 0
    kept: int = 0
    merged_groups: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "raw": self.raw,
            "invalid": self.invalid,
            "duplicates": self.duplicates,
            "outliers": self.outliers,
            "kept": self.kept,
            "merged_groups": self.merged_groups,
        }


def _to_halfwidth(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def clean_title(title: str) -> str:
    """去掉促销词、括号广告、多余空白，保留型号核心信息。"""
    text = _to_halfwidth(str(title or ""))
    text = text.replace("&nbsp;", " ")

    def _strip_bracket(match: re.Match[str]) -> str:
        inner = match.group(1)
        return "" if any(word in inner for word in PROMO_WORDS) else inner

    text = BRACKET_RE.sub(_strip_bracket, text)
    for word in PROMO_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"[|丨•·]+", " ", text)
    text = SPACE_RE.sub(" ", text).strip(" -_/")
    return text


def _signature(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]+", "", title).lower()


def _tokens(title: str) -> set[str]:
    text = _signature(title)
    chars = re.findall(r"[\u4e00-\u9fa5]", text)
    bigrams = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}
    latin = set(re.findall(r"[a-z]{2,}|\d+", text))
    return bigrams | latin


def _similar(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return SequenceMatcher(None, a, b).ratio()
    return len(left & right) / len(left | right)


def _normalize(item: Listing) -> bool:
    item.title = clean_title(item.title)
    item.shop = SPACE_RE.sub(" ", str(item.shop or "")).strip() or "未知店铺"
    try:
        item.price = round(float(item.price), 2)
    except (TypeError, ValueError):
        return False
    try:
        item.sales = max(0, int(item.sales or 0))
    except (TypeError, ValueError):
        item.sales = 0
    try:
        item.shop_rating = round(float(item.shop_rating or 0), 2)
    except (TypeError, ValueError):
        item.shop_rating = 0.0
    if not item.model_name:
        item.model_name = item.title
    return bool(item.title) and 0.01 <= item.price <= 1_000_000 and item.url


def _dedupe(listings: list[Listing]) -> tuple[list[Listing], int]:
    """同平台同店铺的重复挂牌：保留价格更低的一条。"""
    kept: list[Listing] = []
    buckets: dict[tuple[str, str], list[Listing]] = {}
    dropped = 0
    for item in sorted(listings, key=lambda x: x.price):
        bucket = buckets.setdefault((item.platform, item.shop), [])
        duplicate = False
        for existing in bucket:
            ratio = item.price / existing.price if existing.price else 9.9
            if not 0.8 <= ratio <= 1.25:
                continue
            if _similar(item.title, existing.title) >= 0.92:
                duplicate = True
                break
        if duplicate:
            dropped += 1
        else:
            bucket.append(item)
            kept.append(item)
    return kept, dropped


def _assign_groups(listings: list[Listing]) -> int:
    """跨平台型号归组；真实数据没有 model_key 时按标题相似度聚类。"""
    clusters: dict[str, str] = {}
    reps: list[tuple[str, str]] = []  # (key, title)
    synthetic = 0
    for item in listings:
        if item.model_key:
            clusters.setdefault(item.model_key, item.model_name or item.title)
            continue
        best_key, best_score = "", 0.0
        for key, rep_title in reps:
            score = _similar(item.title, rep_title)
            if score > best_score:
                best_key, best_score = key, score
        if best_key and best_score >= 0.55:
            item.model_key = best_key
            if len(item.title) < len(clusters.get(best_key, item.title)):
                clusters[best_key] = item.title
        else:
            item.model_key = f"cluster-{synthetic}"
            synthetic += 1
            clusters[item.model_key] = item.title
            reps.append((item.model_key, item.title))
    for item in listings:
        item.model_name = clusters.get(item.model_key, item.model_name or item.title)
    return len({item.model_key for item in listings})


def _drop_outliers(listings: list[Listing]) -> tuple[list[Listing], int]:
    """同型号内价格显著偏离的引流款/异常标价。"""
    groups: dict[str, list[Listing]] = {}
    for item in listings:
        groups.setdefault(item.model_key, []).append(item)
    removed_ids: set[int] = set()
    for group in groups.values():
        prices = [item.price for item in group]
        if len(prices) < 3:
            continue
        median = statistics.median(prices)
        for item in group:
            if item.price < median * 0.45 or item.price > median * 2.8:
                removed_ids.add(id(item))
    return [item for item in listings if id(item) not in removed_ids], len(removed_ids)


def clean_listings(raw: list[Listing]) -> tuple[list[Listing], CleanStats]:
    stats = CleanStats(raw=len(raw))
    valid: list[Listing] = []
    for item in raw:
        if _normalize(item):
            valid.append(item)
        else:
            stats.invalid += 1

    valid, stats.duplicates = _dedupe(valid)
    stats.merged_groups = _assign_groups(valid)
    valid, stats.outliers = _drop_outliers(valid)
    valid.sort(key=lambda item: item.price)
    stats.kept = len(valid)
    return valid, stats
