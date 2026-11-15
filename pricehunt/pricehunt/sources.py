"""采集层：三个平台的适配器 + 离线演示数据源 + 自动降级调度。

真实平台普遍存在风控（京东会返回验证页、淘宝搜索需要登录态、拼多多搜索需要
anti_content 签名），因此本模块采用「适配器 + 可插拔凭证 + 自动降级」的设计：
    - 配置 Cookie 后，可在真实网络环境抓取；
    - 抓不到时自动降级到确定性演示数据源，保证命令行与网页始终可运行、可演示。
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from .models import PLATFORM_KEYS, Listing, SourceResult, platform_name

try:  # 可选依赖，缺失时只影响真实采集
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


class SourceError(RuntimeError):
    """单个平台采集失败。"""


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _headers(platform: str) -> dict[str, str]:
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    cookie = os.environ.get(f"{platform.upper()}_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _get(url: str, platform: str, params: dict[str, Any] | None = None, timeout: int = 8):
    if requests is None:
        raise SourceError("缺少 requests 依赖，无法实时采集")
    try:
        resp = requests.get(url, params=params, headers=_headers(platform), timeout=timeout)
        resp.raise_for_status()
        return resp
    except Exception as exc:  # 网络、超时、状态码
        raise SourceError(f"{platform_name(platform)} 请求失败：{type(exc).__name__}") from exc


def _to_price(text: str | float) -> float:
    if isinstance(text, (int, float)):
        return round(float(text), 2)
    match = re.search(r"\d+(?:\.\d+)?", str(text).replace(",", ""))
    return round(float(match.group()), 2) if match else 0.0


def _to_sales(text: str | int) -> int:
    if isinstance(text, int):
        return text
    raw = str(text).replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(万)?", raw)
    if not match:
        return 0
    value = float(match.group(1))
    if match.group(2):
        value *= 10000
    return int(value)


# ---------------------------------------------------------------------------
# 真实平台适配器
# ---------------------------------------------------------------------------
class JDCollector:
    key = "jd"
    label = "京东"

    def fetch(self, keyword: str, limit: int = 40) -> list[Listing]:
        resp = _get(
            "https://search.jd.com/Search",
            self.key,
            params={"keyword": keyword, "enc": "utf-8", "page": 1},
        )
        resp.encoding = resp.apparent_encoding or "utf-8"
        if BeautifulSoup is None:
            raise SourceError("缺少 beautifulsoup4 依赖")
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("li.gl-item")
        if not items:
            raise SourceError("京东返回风控校验页，未解析到商品（配置 JD_COOKIE 或代理后重试）")

        rows: list[dict[str, Any]] = []
        for li in items[: limit * 2]:
            sku = li.get("data-sku", "").strip()
            name_el = li.select_one(".p-name em")
            price_el = li.select_one(".p-price i")
            shop_el = li.select_one(".p-shop a")
            if not (sku and name_el):
                continue
            rows.append(
                {
                    "sku": sku,
                    "title": name_el.get_text(" ", strip=True),
                    "price": _to_price(price_el.get_text(strip=True)) if price_el else 0.0,
                    "shop": shop_el.get_text(strip=True) if shop_el else "京东店铺",
                    "url": f"https://item.jd.com/{sku}.html",
                }
            )
        if not rows:
            raise SourceError("京东页面结构变化，未匹配到商品节点")

        # 搜索页价格是异步渲染的，用公开价格接口补齐
        prices = self._fetch_prices([row["sku"] for row in rows])
        listings: list[Listing] = []
        for row in rows:
            price = prices.get(row["sku"]) or row["price"]
            if price <= 0:
                continue
            listings.append(
                Listing(
                    platform=self.key,
                    title=row["title"],
                    price=price,
                    sales=0,
                    shop=row["shop"],
                    shop_rating=0.0,
                    url=row["url"],
                    sku=row["sku"],
                    source="live",
                )
            )
        if not listings:
            raise SourceError("京东商品价格解析为空")
        return listings[:limit]

    @staticmethod
    def _fetch_prices(skus: list[str]) -> dict[str, float]:
        if not skus:
            return {}
        try:
            resp = requests.get(  # type: ignore[union-attr]
                "https://p.3.cn/prices/mgets",
                params={"skuIds": ",".join(f"J_{s}" for s in skus[:50]), "type": 1},
                headers={"User-Agent": UA, "Referer": "https://search.jd.com/"},
                timeout=8,
            )
            data = resp.json()
            return {str(item["id"]).replace("J_", ""): _to_price(item["p"]) for item in data}
        except Exception:
            return {}


class TaobaoCollector:
    key = "tb"
    label = "淘宝"

    def fetch(self, keyword: str, limit: int = 40) -> list[Listing]:
        if not os.environ.get("TB_COOKIE"):
            raise SourceError("淘宝搜索需要登录态，请配置 TB_COOKIE 环境变量")
        resp = _get("https://s.taobao.com/search", self.key, params={"q": keyword})
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
        if "登录" in html and "raw_title" not in html:
            raise SourceError("淘宝返回登录/验证页（TB_COOKIE 失效或触发风控）")

        titles = re.findall(r'"raw_title"\s*:\s*"(.*?)"', html)
        prices = re.findall(r'"view_price"\s*:\s*"([\d.]+)"', html)
        sales = re.findall(r'"view_sales"\s*:\s*"([^"]*)"', html)
        shops = re.findall(r'"nick"\s*:\s*"([^"]*)"', html)
        ids = re.findall(r'"nid"\s*:\s*"(\d+)"', html)
        if not titles or not prices:
            raise SourceError("淘宝页面数据结构变化，未解析到商品")

        listings: list[Listing] = []
        for i, raw_title in enumerate(titles[:limit]):
            price = _to_price(prices[i]) if i < len(prices) else 0
            if price <= 0:
                continue
            item_id = ids[i] if i < len(ids) else str(abs(hash(raw_title)) % 10**12)
            listings.append(
                Listing(
                    platform=self.key,
                    title=raw_title.replace("&nbsp;", " "),
                    price=price,
                    sales=_to_sales(sales[i]) if i < len(sales) else 0,
                    shop=shops[i] if i < len(shops) else "淘宝店铺",
                    shop_rating=0.0,
                    url=f"https://item.taobao.com/item.htm?id={item_id}",
                    sku=item_id,
                    source="live",
                )
            )
        if not listings:
            raise SourceError("淘宝商品价格解析为空")
        return listings


class PddCollector:
    key = "pdd"
    label = "拼多多"

    def fetch(self, keyword: str, limit: int = 40) -> list[Listing]:
        if not os.environ.get("PDD_COOKIE"):
            raise SourceError("拼多多无公开搜索页，请配置 PDD_COOKIE 与 anti_content 签名服务")
        resp = _get(
            "https://mobile.yangkeduo.com/proxy/api/search",
            self.key,
            params={"q": keyword, "page": 1, "size": min(limit, 50)},
        )
        try:
            payload = resp.json()
        except Exception as exc:
            raise SourceError("拼多多返回非 JSON（风控拦截）") from exc

        items = payload.get("items") or payload.get("goods_list") or []
        listings: list[Listing] = []
        for item in items:
            goods_id = str(item.get("goods_id") or item.get("goodsId") or "")
            title = item.get("goods_name") or item.get("goodsName") or ""
            price_info = item.get("price_info") or {}
            price = _to_price(
                item.get("price")
                or item.get("min_group_price", 0) / 100
                or price_info.get("line_price", 0)
            )
            if not (goods_id and title and price > 0):
                continue
            listings.append(
                Listing(
                    platform=self.key,
                    title=title,
                    price=price,
                    sales=_to_sales(item.get("sales_tip") or item.get("sales", 0)),
                    shop=item.get("mall_name") or "拼多多店铺",
                    shop_rating=0.0,
                    url=f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}",
                    sku=goods_id,
                    source="live",
                )
            )
        if not listings:
            raise SourceError("拼多多商品解析为空")
        return listings[:limit]


LIVE_COLLECTORS = {
    "jd": JDCollector(),
    "tb": TaobaoCollector(),
    "pdd": PddCollector(),
}


# ---------------------------------------------------------------------------
# 演示数据源：确定性生成，同一关键词每次结果一致，可复现
# ---------------------------------------------------------------------------
CATALOG: dict[str, list[tuple[str, str, str, str, float]]] = {
    "机械键盘": [
        ("Keychron K8 Pro 87键 三模热插拔", "keychron-k8-pro", "Keychron", "keychron", 599),
        ("达尔优 A87 Pro 87键 有线机械键盘", "dareu-a87-pro", "达尔优", "dareu", 329),
        ("罗技 G913 TKL 无线机械键盘", "logitech-g913-tkl", "罗技", "logitech", 1099),
        ("狼蛛 F87 87键 客制化机械键盘", "aula-f87", "狼蛛", "aula", 199),
        ("CHERRY MX 3.0S 108键 机械键盘", "cherry-mx30s", "CHERRY", "cherry", 499),
        ("VGN N75 75键 gasket 结构", "vgn-n75", "VGN", "vgn", 169),
        ("雷蛇 黑寡妇蜘蛛 V4 75%", "razer-blackwidow-v4", "雷蛇", "razer", 899),
        ("京东京造 K87 机械键盘", "jdz-k87", "京东京造", "jdz", 259),
    ],
    "蓝牙耳机": [
        ("索尼 WF-1000XM5 真无线降噪耳机", "sony-wf1000xm5", "索尼", "sony", 1899),
        ("Apple AirPods Pro 2 USB-C", "apple-airpods-pro2", "Apple", "apple", 1799),
        ("华为 FreeBuds Pro 3 真无线耳机", "huawei-freebuds-pro3", "华为", "huawei", 1199),
        ("小米 Buds 5 半入耳降噪耳机", "xiaomi-buds5", "小米", "xiaomi", 399),
        ("漫步者 Lolli Pro 3 主动降噪耳机", "edifier-lolli-pro3", "漫步者", "edifier", 349),
        ("OPPO Enco X3 真无线降噪耳机", "oppo-enco-x3", "OPPO", "oppo", 899),
        ("倍思 E8 半入耳蓝牙耳机", "baseus-e8", "倍思", "baseus", 129),
    ],
    "空气炸锅": [
        ("美的 KFR-50 5.5L 空气炸锅", "midea-kfr50", "美的", "midea", 329),
        ("苏泊尔 6L 可视空气炸锅", "supor-6l", "苏泊尔", "supor", 399),
        ("九阳 5L 免翻面空气炸锅", "joyoung-5l", "九阳", "joyoung", 269),
        ("飞利浦 HD9252 4.1L 空气炸锅", "philips-hd9252", "飞利浦", "philips", 699),
        ("米家 4L 智能空气炸锅", "mijia-4l", "小米", "xiaomi", 299),
        ("山本 6L 家用大容量空气炸锅", "yamamoto-6l", "山本", "yamamoto", 239),
    ],
    "跑步鞋": [
        ("耐克 Pegasus 41 男款跑鞋", "nike-pegasus41", "耐克", "nike", 899),
        ("阿迪达斯 Ultraboost 5 跑鞋", "adidas-ub5", "阿迪达斯", "adidas", 1299),
        ("李宁 赤兔 7 Pro 跑鞋", "lining-chitu7pro", "李宁", "lining", 499),
        ("安踏 马赫 4 跑步鞋", "anta-mahe4", "安踏", "anta", 399),
        ("特步 260 2.0 竞速跑鞋", "xtep-260-2", "特步", "xtep", 459),
        ("亚瑟士 GEL-KAYANO 30 跑鞋", "asics-kayano30", "亚瑟士", "asics", 1099),
        ("索康尼 菁华 15 跑鞋", "saucony-kinvara15", "索康尼", "saucony", 799),
    ],
    "咖啡机": [
        ("德龙 ECAM22.110 全自动咖啡机", "delonghi-ecam22", "德龙", "delonghi", 3499),
        ("飞利浦 EP2231 全自动萃取咖啡机", "philips-ep2231", "飞利浦", "philips", 2999),
        ("柏翠 PE3320 半自动咖啡机", "petrus-pe3320", "柏翠", "petrus", 699),
        ("米家 胶囊咖啡机", "mijia-capsule", "小米", "xiaomi", 399),
        ("Nespresso Essenza Mini 胶囊机", "nespresso-mini", "Nespresso", "nespresso", 899),
        ("摩飞 MR4266 便携咖啡机", "morphy-mr4266", "摩飞", "morphy", 399),
    ],
    "显示器": [
        ("戴尔 U2723QE 27英寸 4K 显示器", "dell-u2723qe", "戴尔", "dell", 3299),
        ("AOC Q27G2S 27英寸 2K 165Hz", "aoc-q27g2s", "AOC", "aoc", 1499),
        ("小米 27英寸 2K 165Hz 显示器", "xiaomi-27-2k", "小米", "xiaomi", 999),
        ("华硕 VG27AQ 27英寸 2K 电竞屏", "asus-vg27aq", "华硕", "asus", 1999),
        ("HKC 27英寸 2K 180Hz 显示器", "hkc-27-2k", "HKC", "hkc", 899),
        ("LG 27GP850 27英寸 2K 165Hz", "lg-27gp850", "LG", "lg", 2499),
    ],
}

GENERIC_BRANDS = [
    ("小米", "xiaomi"),
    ("华为", "huawei"),
    ("联想", "lenovo"),
    ("美的", "midea"),
    ("九阳", "joyoung"),
    ("苏泊尔", "supor"),
    ("飞利浦", "philips"),
    ("京东京造", "jdz"),
    ("网易严选", "yanxuan"),
    ("德尔玛", "deerma"),
]
GENERIC_SPECS = ["旗舰款", "家用升级版", "Pro 2026 新款", "经典款", "轻享版", "高配版", "礼盒装"]
PRICE_LADDER = [89, 129, 169, 199, 259, 329, 459, 599, 799, 999, 1299, 1599]


def _rng(*parts: str) -> random.Random:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(digest)


def _models_for(keyword: str) -> tuple[str, list[tuple[str, str, str, str, float]]]:
    kw = keyword.strip()
    for catalog_key, models in CATALOG.items():
        if catalog_key in kw or kw in catalog_key:
            return catalog_key, models
    rng = _rng("catalog", kw)
    brands = rng.sample(GENERIC_BRANDS, 7)
    models = []
    for i, (brand, brand_en) in enumerate(brands):
        spec = rng.choice(GENERIC_SPECS)
        price = float(rng.choice(PRICE_LADDER))
        models.append((f"{brand} {kw} {spec}", f"gen-{brand_en}-{i}", brand, brand_en, price))
    return kw, models


def _build_demo(keyword: str) -> SourceResult:
    catalog_key, models = _models_for(keyword)
    listings: list[Listing] = []
    platform_counts: dict[str, int] = {key: 0 for key in PLATFORM_KEYS}

    for name, model_key, brand, brand_en, base_price in models:
        plan_rng = _rng("plan", catalog_key, model_key)
        plan = ["jd"]
        if plan_rng.random() < 0.82:
            plan.append("tb")
        if plan_rng.random() < 0.68:
            plan.append("pdd")
        if len(plan) < 2:
            plan.append("tb" if "tb" not in plan else "pdd")

        # 型号级基础销量：各平台在此之上浮动，保证跨平台销量具备可比性
        cap = 4.45 if base_price < 300 else (3.75 if base_price < 1000 else 3.25)
        base_sales = 10 ** _rng("sales", catalog_key, model_key).uniform(2.0, cap)
        # 部分型号在某个平台有限时促销，避免「拼多多永远最便宜」的呆板结论
        promo_rng = _rng("promo", catalog_key, model_key)
        promo_platform = promo_rng.choice(["jd", "tb", "pdd", None, None])

        for platform in plan:
            pr = _rng("listing", catalog_key, model_key, platform)
            factor = {"jd": 1.0, "tb": 0.968, "pdd": 0.915}[platform] + pr.uniform(-0.05, 0.05)
            if platform == promo_platform:
                factor -= 0.06
            price = round(base_price * factor, 2)
            if pr.random() < 0.25:
                price = round(price) - 0.1
                price = round(price, 2)

            sales = int(
                base_sales
                * {"jd": 1.0, "tb": 1.12, "pdd": 1.55}[platform]
                * pr.uniform(0.72, 1.28)
            )
            sales = max(60, int(round(sales, -1)))

            suffixes = {
                "jd": ["京东自营旗舰店", "官方旗舰店"],
                "tb": ["官方旗舰店", "数码专营店", "品牌直营店"],
                "pdd": ["官方旗舰店", "品牌黑标店", "百亿补贴店"],
            }
            noise = {
                "jd": ["", " 官方正品 全国联保"],
                "tb": [" 包邮 官方正品", ""],
                "pdd": [" 百亿补贴 顺丰包邮", " 官方正品"],
            }
            rating_range = {"jd": (4.72, 4.96), "tb": (4.62, 4.90), "pdd": (4.55, 4.86)}

            listings.append(
                Listing(
                    platform=platform,
                    title=name + pr.choice(noise[platform]),
                    price=price,
                    sales=sales,
                    shop=f"{brand}{pr.choice(suffixes[platform])}",
                    shop_rating=round(pr.uniform(*rating_range[platform]), 2),
                    url={
                        "jd": f"https://item.jd.com/{pr.randint(100000000, 999999999)}.html",
                        "tb": f"https://item.taobao.com/item.htm?id={pr.randint(10**13, 10**14 - 1)}",
                        "pdd": f"https://mobile.yangkeduo.com/goods.html?goods_id={pr.randint(10**11, 10**12 - 1)}",
                    }[platform],
                    sku=str(pr.randint(10**9, 10**10 - 1)),
                    list_price=round(price * (1 + pr.uniform(0.08, 0.32)), 2),
                    coupon=pr.choice(["", "", "满199减20", "店铺券 10 元", "限时立减"]),
                    model_key=model_key,
                    model_name=name,
                    source="demo",
                    is_demo=True,
                )
            )
            platform_counts[platform] += 1

    # 注入「同店重复挂牌」，用于演示去重
    dup_candidates = [item for item in listings if item.sales > 800][:2] or listings[:2]
    for index, origin in enumerate(dup_candidates):
        dup_rng = _rng("dup", catalog_key, origin.sku, str(index))
        listings.append(
            replace(
                origin,
                title="【限时秒杀】" + origin.title,
                price=round(origin.price * 0.985, 2),
                sku=str(dup_rng.randint(10**9, 10**10 - 1)),
                coupon="秒杀券",
                url=origin.url,
            )
        )

    # 注入「9.9 引流款」，用于演示异常价格剔除
    outlier_origin = listings[0]
    out_rng = _rng("outlier", catalog_key, outlier_origin.model_key)
    listings.append(
        replace(
            outlier_origin,
            title=outlier_origin.title + " 引流款",
            price=9.9,
            list_price=99.0,
            sales=9999,
            sku=str(out_rng.randint(10**9, 10**10 - 1)),
        )
    )

    # 30 天价格走势（型号维度，取各平台最低价的模拟序列）
    min_price_by_model: dict[str, float] = {}
    model_name_by_key: dict[str, str] = {}
    for item in listings:
        if item.price < 12:  # 跳过引流款
            continue
        key = item.model_key
        min_price_by_model[key] = min(min_price_by_model.get(key, 1e9), item.price)
        model_name_by_key[key] = item.model_name

    today = date.today()
    history: dict[str, list[dict[str, Any]]] = {}
    for key, end_price in min_price_by_model.items():
        hr = _rng("history", catalog_key, key)
        prices: list[float] = []
        price = end_price * hr.uniform(1.02, 1.16)
        for _ in range(30):
            price *= 1 + hr.uniform(-0.009, 0.007)
            if hr.random() < 0.07:
                price *= hr.uniform(0.93, 0.97)
            prices.append(price)
        scale = end_price / prices[-1]
        history[key] = [
            {
                "date": (today - timedelta(days=29 - i)).strftime("%m-%d"),
                "price": round(prices[i] * scale, 2),
            }
            for i in range(30)
        ]

    return SourceResult(
        listings=listings,
        requested_source="demo",
        source_label="演示数据源（确定性模拟，用于功能演示）",
        is_demo=True,
        fallback=False,
        warnings=[],
        platform_counts=platform_counts,
        history=history,
    )


class DemoSource:
    def fetch(self, keyword: str, limit: int = 40, **_: Any) -> SourceResult:
        time.sleep(0.15)  # 模拟网络耗时，便于前端展示采集流水线
        return _build_demo(keyword)


# ---------------------------------------------------------------------------
# 调度：实时优先 + 自动降级
# ---------------------------------------------------------------------------
def collect(
    keyword: str,
    platforms: list[str] | None = None,
    source: str = "demo",
    limit: int = 40,
    timeout: int = 8,
) -> SourceResult:
    keyword = keyword.strip()
    if not keyword:
        raise SourceError("关键词不能为空")
    platforms = [p for p in (platforms or PLATFORM_KEYS) if p in PLATFORM_KEYS] or list(PLATFORM_KEYS)

    if source == "demo":
        return DemoSource().fetch(keyword, limit)

    warnings: list[str] = []
    listings: list[Listing] = []
    counts: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=len(platforms)) as pool:
        futures = {
            pool.submit(LIVE_COLLECTORS[p].fetch, keyword, limit): p for p in platforms
        }
        try:
            for future in as_completed(futures, timeout=timeout + 4):
                platform = futures[future]
                try:
                    part = future.result()
                    listings.extend(part)
                    counts[platform] = len(part)
                except SourceError as exc:
                    warnings.append(f"{platform_name(platform)}：{exc}")
                except Exception as exc:  # pragma: no cover - 防御式兜底
                    warnings.append(f"{platform_name(platform)}：{type(exc).__name__}")
        except TimeoutError:
            for future, platform in futures.items():
                if not future.done():
                    future.cancel()
                    warnings.append(f"{platform_name(platform)}：请求超时")

    if not listings:
        if source == "auto":
            demo = DemoSource().fetch(keyword, limit)
            demo.requested_source = "auto"
            demo.source_label = "演示数据源（实时采集不可用，已自动降级）"
            demo.fallback = True
            demo.warnings = warnings + ["实时采集全部失败，已自动降级到演示数据源"]
            return demo
        detail = "；".join(warnings) or "无可用数据"
        raise SourceError(f"实时采集失败：{detail}")

    return SourceResult(
        listings=listings,
        requested_source=source,
        source_label="实时数据源" + ("（部分平台降级）" if warnings else ""),
        is_demo=False,
        fallback=False,
        warnings=warnings,
        platform_counts=counts,
    )
