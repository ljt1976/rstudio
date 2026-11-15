"""命令行入口：search / demo / serve。"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata

from .models import PLATFORM_KEYS, fmt_money
from .pipeline import RunOutput, run_search, save_artifacts
from .sources import SourceError

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

ANSI = {
    "dim": "\033[2m",
    "bold": "\033[1m",
    "reset": "\033[0m",
    "accent": "\033[38;5;208m",
    "blue": "\033[38;5;33m",
    "green": "\033[38;5;35m",
    "jd": "\033[38;5;160m",
    "tb": "\033[38;5;172m",
    "pdd": "\033[38;5;163m",
}


def _color(text: str, style: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ANSI.get(style, '')}{text}{ANSI['reset']}"


def _width(text: str) -> int:
    plain = ANSI_RE.sub("", text)
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in plain)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _trim(text: str, width: int) -> str:
    if _width(text) <= width:
        return text
    result, used = "", 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used + step > width - 1:
            break
        result += ch
        used += step
    return result + "…"


def _sales(value: int) -> str:
    return f"{value / 10000:.1f}万" if value >= 10000 else str(value)


def _row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(_pad(cell, width) for cell, width in zip(cells, widths)).rstrip()


def print_report(out: RunOutput, colors: bool, limit: int, sort_key: str) -> None:
    result = out.result
    meta, stats = result.meta, result.stats
    accent = lambda text: _color(text, "accent", colors)  # noqa: E731
    dim = lambda text: _color(text, "dim", colors)  # noqa: E731

    print()
    print(accent("◆ PriceHunt") + f"  「{result.keyword}」全网比价")
    print(dim(f"  数据源：{meta['source_label']} · 采集 {result.generated_at} · 耗时 {result.duration_ms}ms"))
    clean = meta["clean"]
    print(
        dim(
            f"  流水线：原始 {clean['raw']} 条 → 去重 {clean['duplicates']} → 剔除异常 {clean['outliers']} "
            f"→ 有效 {clean['kept']} 条 / {stats['group_count']} 个型号"
        )
    )
    for warning in meta.get("warnings", []):
        print(_color(f"  ! {warning}", "tb", colors))

    print()
    print(
        f"  最低价 {_color(fmt_money(stats['min_price']), 'green', colors)}   "
        f"均价 {fmt_money(stats['avg_price'])}   "
        f"最高价差 {stats['max_spread_pct']}%   "
        f"总销量 {_sales(stats['total_sales'])}"
    )

    print()
    print(_color("  推荐结论", "bold", colors))
    for rec in result.recommendations:
        item = rec["listing"]
        print(
            f"  ★ {_color(_pad(rec['label'], 14), 'accent', colors)}"
            f"{_color(_pad(fmt_money(item['price']), 11), 'bold', colors)}"
            f"{_color(_pad(item['platform_name'], 8), item['platform'], colors)}"
            f"{_trim(item['title'], 40)}"
        )

    ordered = list(result.listings)
    if sort_key == "sales":
        ordered.sort(key=lambda x: -x.sales)
    elif sort_key == "value":
        ordered.sort(key=lambda x: -x.value_score)
    elif sort_key == "rating":
        ordered.sort(key=lambda x: -x.shop_rating)

    print()
    sort_labels = {"price": "价格", "sales": "销量", "value": "性价比", "rating": "评分"}
    print(_color(f"  商品报价（按{sort_labels[sort_key]}排序）", "bold", colors))
    header = ["#", "平台", "商品", "到手价", "销量", "评分", "性价比", "标注"]
    widths = [3, 7, 40, 11, 8, 6, 7, 18]
    print(dim("  " + _row(header, widths)))
    print(dim("  " + "─" * (sum(widths) + 2 * (len(widths) - 1))))
    for index, item in enumerate(ordered[:limit], start=1):
        cells = [
            str(index),
            _color(item.platform_name, item.platform, colors),
            _trim(item.title, 40),
            fmt_money(item.price),
            _sales(item.sales),
            f"{item.shop_rating:.2f}" if item.shop_rating else "—",
            f"{item.value_score:.1f}",
            " ".join(item.tags[:2]),
        ]
        print("  " + _row(cells, widths))
    if len(ordered) > limit:
        print(dim(f"  … 其余 {len(ordered) - limit} 条见完整报告"))

    print()
    print(dim(f"  性价比指数：{meta['scoring']['formula']}"))
    print()


def _parse_platforms(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    invalid = [value for value in values if value not in PLATFORM_KEYS]
    if invalid:
        raise SystemExit(f"未知平台：{', '.join(invalid)}（可选：{', '.join(PLATFORM_KEYS)}）")
    return values or None


def cmd_search(args: argparse.Namespace) -> int:
    try:
        out = run_search(
            args.keyword,
            platforms=_parse_platforms(args.platforms),
            source=args.source,
            limit=args.limit,
        )
    except SourceError as exc:
        print(_color(f"采集失败：{exc}", "jd", True), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(out.result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print_report(out, colors=not args.no_color, limit=args.show, sort_key=args.sort)

    saved: list[str] = []
    if args.csv or args.report:
        if args.csv:
            from .storage import write_csv

            saved.append(str(write_csv(out.result.listings, args.csv)))
        if args.report:
            from .report import write_report

            saved.append(str(write_report(out.result.to_dict(), args.report)))
    elif not args.no_artifacts:
        paths = save_artifacts(out)
        saved = [str(paths["html"]), str(paths["csv"])]
    if saved:
        print("  已生成：")
        for path in saved:
            print(f"    {path}")
        print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    try:
        out = run_search(args.keyword, source="demo", limit=60)
    except SourceError as exc:
        print(f"演示运行失败：{exc}", file=sys.stderr)
        return 1
    print_report(out, colors=not args.no_color, limit=args.show, sort_key="price")
    paths = save_artifacts(out, args.out)
    print("  演示产物：")
    print(f"    HTML 报告  {paths['html']}")
    print(f"    CSV 数据   {paths['csv']}")
    print()
    print("  提示：运行 `python -m pricehunt serve` 可打开交互式演示网页。")
    print()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .webapp import serve

    serve(host=args.host, port=args.port, open_browser=args.open)
    return 0


def cmd_platforms(_: argparse.Namespace) -> int:
    from .models import PLATFORMS

    print("支持的平台：")
    for key in PLATFORM_KEYS:
        print(f"  {key:<4} {PLATFORMS[key]['name']:<6} {PLATFORMS[key]['home']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricehunt",
        description="PriceHunt · 电商商品价格自动化采集与对比工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            '  python -m pricehunt search "机械键盘"\n'
            '  python -m pricehunt search "蓝牙耳机" --platforms jd,tb --source auto --sort value\n'
            "  python -m pricehunt demo\n"
            "  python -m pricehunt serve --port 8020\n"
        ),
    )
    parser.add_argument("--version", action="version", version="PriceHunt 1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="按关键词采集并生成对比报告")
    search.add_argument("keyword", help="搜索关键词，例如：机械键盘")
    search.add_argument(
        "--platforms", default=None, help="平台，逗号分隔：jd,tb,pdd（默认全部）"
    )
    search.add_argument(
        "--source", choices=["demo", "live", "auto"], default="auto", help="数据源（默认 auto：实时优先，失败降级）"
    )
    search.add_argument("--limit", type=int, default=40, help="单平台采集上限（默认 40）")
    search.add_argument("--sort", choices=["price", "sales", "value", "rating"], default="price", help="终端展示排序")
    search.add_argument("--show", type=int, default=15, help="终端展示条数（默认 15）")
    search.add_argument("--json", action="store_true", help="输出完整 JSON 到 stdout")
    search.add_argument("--csv", default=None, help="CSV 输出路径")
    search.add_argument("--report", default=None, help="HTML 报告输出路径")
    search.add_argument("--no-artifacts", action="store_true", help="不写默认报告文件")
    search.add_argument("--no-color", action="store_true", help="关闭终端颜色")
    search.set_defaults(func=cmd_search)

    demo = sub.add_parser("demo", help="用内置示例关键词跑通全流程")
    demo.add_argument("keyword", nargs="?", default="机械键盘", help="示例关键词（默认：机械键盘）")
    demo.add_argument("--show", type=int, default=15, help="终端展示条数")
    demo.add_argument("--out", default="out/sessions", help="产物目录")
    demo.add_argument("--no-color", action="store_true", help="关闭终端颜色")
    demo.set_defaults(func=cmd_demo)

    serve = sub.add_parser("serve", help="启动交互式演示网页 + 本地 API")
    serve.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    serve.add_argument("--port", type=int, default=8020, help="监听端口（默认 8020）")
    serve.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    serve.set_defaults(func=cmd_serve)

    platforms = sub.add_parser("platforms", help="查看支持的平台")
    platforms.set_defaults(func=cmd_platforms)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
