#!/usr/bin/env python3
"""Local DEV.to-skinned preview for articles/*.md (approximate Forem look).

Usage:
  python3 preview/preview.py
  python3 preview/preview.py articles/art0144.md
  python3 preview/preview.py --port 8765 articles/art0144.md

Requires: pip install -r preview/requirements.txt
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

try:
    import markdown
except ImportError:
    print(
        "Missing dependency: markdown\n"
        "  python3 -m pip install -r preview/requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
STYLE = Path(__file__).resolve().parent / "style.css"

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
GITHUB_RAW_IMG_RE = re.compile(
    r"(https://github\.com/jdevto/blog/raw/[^/\s)]+/images/)([^)\s]+)"
)
MD_EXTENSIONS = [
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
    "markdown.extensions.smarty",
]


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            value = value[1:-1]
        meta[key] = value
    return meta, text[match.end() :]


def rewrite_images(body: str) -> str:
    # Point published GitHub raw image URLs at the local /images/ tree.
    body = GITHUB_RAW_IMG_RE.sub(r"/images/\2", body)
    body = body.replace("](../images/", "](/images/")
    body = body.replace("](images/", "](/images/")
    return body


def render_markdown(body: str) -> str:
    return markdown.markdown(rewrite_images(body), extensions=MD_EXTENSIONS)


def split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in parts if p]


def article_paths() -> list[Path]:
    return sorted(ARTICLES.glob("art*.md"))


def load_article(path: Path) -> tuple[dict[str, Any], str]:
    path = path.resolve()
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    meta.setdefault("title", path.stem)
    meta["_file"] = path.name
    meta["_path"] = str(path.relative_to(ROOT))
    meta["_mtime"] = path.stat().st_mtime_ns
    return meta, body


def page_shell(title: str, body_html: str, *, reload_path: str | None = None) -> bytes:
    css = STYLE.read_text(encoding="utf-8")
    reload_js = ""
    if reload_path:
        reload_js = f"""
<script>
(() => {{
  const path = {reload_path!r};
  let last = null;
  async function tick() {{
    try {{
      const res = await fetch('/__mtime?path=' + encodeURIComponent(path), {{cache: 'no-store'}});
      if (!res.ok) return;
      const data = await res.json();
      if (last === null) last = data.mtime;
      else if (data.mtime !== last) location.reload();
    }} catch (_) {{}}
  }}
  setInterval(tick, 800);
}})();
</script>
"""
    theme_js = """
<script>
(() => {
  const KEY = 'devto-preview-theme';
  const root = document.documentElement;
  const btn = document.getElementById('theme-toggle');

  function systemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function current() {
    return root.getAttribute('data-theme') || systemTheme();
  }

  function apply(theme, persist) {
    root.setAttribute('data-theme', theme);
    if (persist) localStorage.setItem(KEY, theme);
    if (btn) btn.textContent = theme === 'dark' ? 'Light' : 'Dark';
    if (btn) btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
  }

  const saved = localStorage.getItem(KEY);
  apply(saved === 'dark' || saved === 'light' ? saved : systemTheme(), false);

  btn?.addEventListener('click', () => {
    apply(current() === 'dark' ? 'light' : 'dark', true);
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem(KEY)) apply(e.matches ? 'dark' : 'light', false);
  });
})();
</script>
"""
    boot_theme = """
<script>
(() => {
  try {
    const saved = localStorage.getItem('devto-preview-theme');
    const theme = saved === 'dark' || saved === 'light'
      ? saved
      : (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  } catch (_) {}
})();
</script>
"""
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{html.escape(title)}</title>
  {boot_theme}
  <style>{css}</style>
</head>
<body>
  <div class="topbar">
    <div class="brand">DEV <span>local preview</span></div>
    <div class="topbar-actions">
      <a href="/">All articles</a>
      <button type="button" class="theme-toggle" id="theme-toggle">Dark</button>
      <span>· approximate skin — not Forem liquid tags</span>
    </div>
  </div>
  <p class="banner">Offline DEV-like layout for this repo. Liquid embeds and true Forem CSS are not rendered.</p>
  {body_html}
  {theme_js}
  {reload_js}
</body>
</html>
"""
    return doc.encode("utf-8")


def render_article_page(path: Path) -> bytes:
    path = path.resolve()
    meta, body = load_article(path)
    title = str(meta.get("title") or path.stem)
    description = str(meta.get("description") or "")
    tags = split_tags(meta.get("tags") if isinstance(meta.get("tags"), str) else None)
    published = str(meta.get("published") or "")
    body_html = render_markdown(body)

    tags_html = "".join(
        f"<li><span>#{html.escape(tag)}</span></li>" for tag in tags
    ) or "<li><span>#untagged</span></li>"

    desc_html = (
        f'<p class="article-desc">{html.escape(description)}</p>' if description else ""
    )
    siblings = article_paths()
    names = [p.name for p in siblings]
    idx = names.index(path.name) if path.name in names else -1
    nav_items = []
    if idx > 0:
        prev = siblings[idx - 1]
        nav_items.append(
            f'<li><a href="/article/{html.escape(prev.name)}">← {html.escape(prev.name)}</a></li>'
        )
    if 0 <= idx < len(siblings) - 1:
        nxt = siblings[idx + 1]
        nav_items.append(
            f'<li><a href="/article/{html.escape(nxt.name)}">→ {html.escape(nxt.name)}</a></li>'
        )

    content = f"""
  <main class="shell">
    <article class="article-card">
      <header class="article-header">
        <ul class="tags">{tags_html}</ul>
        <h1 class="article-title">{html.escape(title)}</h1>
        {desc_html}
        <div class="meta">
          <span class="pill">{html.escape(path.name)}</span>
          <span class="pill">published: {html.escape(published or "—")}</span>
        </div>
      </header>
      <div class="article-body crayons-article__body">
        {body_html}
      </div>
    </article>
    <aside class="side">
      <div class="side-card">
        <h2>Navigate</h2>
        <ul>
          <li><a href="/">Article index</a></li>
          {''.join(nav_items)}
        </ul>
        <p class="hint">Editing this file reloads the page automatically.</p>
      </div>
    </aside>
  </main>
"""
    return page_shell(f"{title} — DEV preview", content, reload_path=path.name)


def render_index() -> bytes:
    items = []
    for path in article_paths():
        meta, _ = load_article(path)
        title = html.escape(str(meta.get("title") or path.stem))
        items.append(
            f'<li><a href="/article/{html.escape(path.name)}">'
            f"{title}"
            f'<span class="file">{html.escape(path.name)}</span>'
            f"</a></li>"
        )
    content = f"""
  <main class="shell">
    <section class="index">
      <h1>Articles</h1>
      <p>DEV-skinned local preview for <code>articles/</code>.</p>
      <ul>{''.join(items)}</ul>
    </section>
  </main>
"""
    return page_shell("Articles — DEV preview", content)


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "DevtoPreview/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in {"/", "/index.html"}:
            return self._send(200, "text/html; charset=utf-8", render_index())

        if path == "/__mtime":
            qs = parse_qs(parsed.query)
            name = (qs.get("path") or [""])[0]
            target = (ARTICLES / Path(name).name).resolve()
            if not str(target).startswith(str(ARTICLES.resolve())) or not target.is_file():
                return self._send(404, "application/json", b'{"error":"missing"}')
            payload = f'{{"mtime":{target.stat().st_mtime_ns}}}'.encode()
            return self._send(200, "application/json", payload)

        if path.startswith("/article/"):
            name = Path(path.removeprefix("/article/")).name
            target = (ARTICLES / name).resolve()
            if not str(target).startswith(str(ARTICLES.resolve())) or not target.is_file():
                return self._send(404, "text/plain; charset=utf-8", b"Article not found\n")
            return self._send(200, "text/html; charset=utf-8", render_article_page(target))

        if path.startswith("/images/"):
            name = Path(path.removeprefix("/images/")).name
            target = (IMAGES / name).resolve()
            if not str(target).startswith(str(IMAGES.resolve())) or not target.is_file():
                return self._send(404, "text/plain; charset=utf-8", b"Image not found\n")
            data = target.read_bytes()
            ctype = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".svg": "image/svg+xml",
                ".webp": "image/webp",
            }.get(target.suffix.lower(), "application/octet-stream")
            return self._send(200, ctype, data)

        if path == "/favicon.ico":
            return self._send(204, "text/plain", b"")

        return self._send(404, "text/plain; charset=utf-8", b"Not found\n")

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def resolve_start_article(arg: str | None) -> Path | None:
    if not arg:
        return None
    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if candidate.is_file():
        return candidate
    by_name = ARTICLES / Path(arg).name
    if by_name.is_file():
        return by_name
    raise SystemExit(f"Article not found: {arg}")


def main() -> None:
    parser = argparse.ArgumentParser(description="DEV.to-skinned local article preview")
    parser.add_argument(
        "article",
        nargs="?",
        help="Path or filename under articles/ (optional; opens index)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5477)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    args = parser.parse_args()

    if not ARTICLES.is_dir():
        raise SystemExit(f"Missing articles directory: {ARTICLES}")

    start = resolve_start_article(args.article)
    ThreadingHTTPServer.allow_reuse_address = True
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), PreviewHandler)
    except OSError as exc:
        raise SystemExit(
            f"Cannot bind {args.host}:{args.port}: {exc}\n"
            f"  Free it with: fuser -k {args.port}/tcp\n"
            f"  Or use another port: python3 preview/preview.py --port 5478 …"
        ) from exc
    base = f"http://{args.host}:{args.port}"
    open_url = f"{base}/article/{start.name}" if start else f"{base}/"

    print(f"DEV-like preview: {open_url}", flush=True)
    print("Ctrl+C to stop", flush=True)

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(open_url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
