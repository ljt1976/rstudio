"""本地演示服务：静态网页 + /api/search 采集接口 + 报告下载。"""
from __future__ import annotations

import json
import sys
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .models import PLATFORM_KEYS
from .pipeline import run_search, save_artifacts
from .sources import SourceError

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
SESSIONS = ROOT / "out" / "sessions"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".csv": "text/csv; charset=utf-8",
}


def _repair_text(text: str) -> str:
    """兼容未做百分号编码的 UTF-8 请求参数（http.server 会按 latin-1 解码）。"""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _prune(keep: int = 80) -> None:
    if not SESSIONS.exists():
        return
    files = sorted(
        (path for path in SESSIONS.iterdir() if path.suffix in {".html", ".csv"}),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in files[keep:]:
        try:
            path.unlink()
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "PriceHunt/1.0"

    # ---------- 基础设施 ----------
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write(f"  [{self.log_date_time_string()}] {fmt % args}\n")

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, download: bool = False) -> None:
        if not path.is_file():
            self._json({"error": "文件不存在"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{quote(path.name)}"')
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---------- 路由 ----------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._file(STATIC / "index.html")
        elif path == "/api/health":
            self._json({"status": "ok", "service": "pricehunt", "version": "1.0.0"})
        elif path == "/api/search":
            self._search(parsed.query)
        elif path.startswith("/static/"):
            name = path[len("/static/") :]
            if "/" in name or name.startswith("."):
                self._json({"error": "非法路径"}, 400)
                return
            self._file(STATIC / name)
        elif path.startswith("/reports/"):
            name = unquote(path[len("/reports/") :])
            if not name or "/" in name or "\\" in name or name.startswith("."):
                self._json({"error": "非法路径"}, 400)
                return
            self._file(SESSIONS / name, download=parsed.query.find("download=1") >= 0)
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self._json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/search":
            self._json({"error": "Not Found"}, 404)
            return
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "请求体不是合法 JSON"}, 400)
            return
        query = "&".join(f"{key}={value}" for key, value in payload.items() if value is not None)
        self._search(query)

    # ---------- 业务 ----------
    def _search(self, query: str) -> None:
        params = parse_qs(query)
        keyword = _repair_text((params.get("keyword") or ["机械键盘"])[0].strip())[:60]
        raw_platforms = (params.get("platforms") or ["jd,tb,pdd"])[0]
        platforms = [p.strip() for p in raw_platforms.split(",") if p.strip() in PLATFORM_KEYS]
        source = (params.get("source") or ["demo"])[0]
        if source not in {"demo", "live", "auto"}:
            source = "demo"
        try:
            limit = max(5, min(100, int((params.get("limit") or ["40"])[0])))
        except ValueError:
            limit = 40

        if not keyword:
            self._json({"error": "请输入搜索关键词"}, 400)
            return
        try:
            out = run_search(keyword, platforms or None, source=source, limit=limit)
        except SourceError as exc:
            self._json({"error": str(exc)}, 502)
            return
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            self._json({"error": f"服务内部错误：{exc}"}, 500)
            return

        try:
            artifacts = save_artifacts(out, SESSIONS)
            artifacts_url = {
                "report": "/reports/" + quote(artifacts["html"].name),
                "csv": "/reports/" + quote(artifacts["csv"].name) + "?download=1",
            }
            _prune()
        except Exception:  # pragma: no cover - 报告失败不影响主流程
            traceback.print_exc()
            artifacts_url = {}

        payload = out.result.to_dict()
        payload["artifacts"] = artifacts_url
        self._json(payload)


def serve(host: str = "127.0.0.1", port: int = 8020, open_browser: bool = False) -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    _prune()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print()
    print("  ◆ PriceHunt 演示服务已启动")
    print(f"    网页地址   {url}")
    print(f"    采集接口   {url}api/search?keyword=机械键盘&source=demo")
    print("    按 Ctrl+C 停止")
    print()
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":  # pragma: no cover
    serve(port=8020)
