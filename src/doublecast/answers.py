"""`show_answer`: the AI's answer, with the real values, opened on the user's screen.

The chat can only show what the AI wrote, which is in stand-ins. This tool takes that answer,
puts the real names and amounts back on this computer, saves it as a page in
~/.doublecast/answers/ and opens it in the browser. Nothing real goes back to the AI: the tool
only replies that the page was shown.
"""

from __future__ import annotations

import datetime as dt
import html
import os
import platform
import re
import subprocess
from pathlib import Path

TOOL = {
    "name": "show_answer",
    "description": (
        "Show the user your answer with the real names and amounts. Call this after every answer that "
        "uses data from Doublecast (folders or a connector such as Power BI): pass the answer as "
        "Markdown, exactly as you wrote it. The real values are put back on the user's computer and "
        "the answer opens in their browser; you only get a confirmation."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short title, e.g. 'Top customers 2026'"},
            "markdown": {"type": "string", "description": "Your answer, in Markdown, with the stand-ins"},
        },
        "required": ["markdown"],
    },
}

_CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--accent:#2f6b55}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--accent:#7fc4a8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 24px 80px}
.tag{display:inline-block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);
border:1px solid var(--accent);border-radius:99px;padding:2px 10px;margin-bottom:14px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px}h2{font-size:21px;margin:32px 0 8px}h3{font-size:18px;margin:24px 0 6px}
.meta{color:var(--muted);font-size:14px;margin-bottom:28px}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:15px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}th{font-weight:600;border-bottom:2px solid var(--fg)}
td.n,th.n{text-align:right}ul,ol{padding-left:22px}code{font-size:14px;background:var(--line);padding:1px 5px;border-radius:4px}
@media (max-width:600px){main{padding:24px 16px 60px}h1{font-size:24px}table{font-size:13px}}
"""


def _inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def _is_num(cell: str) -> bool:
    return bool(re.fullmatch(r"[-+−]?[€$£]?\s?[\d.,]+\s?(%|k|m|M|bn)?", cell.strip()))


def markdown_to_html(md: str) -> str:
    out: list[str] = []
    lines = md.replace("\r\n", "\n").split("\n")
    i, para, lst = 0, [], None

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para = []

    def close_list():
        nonlocal lst
        if lst:
            out.append(f"</{lst}>")
            lst = None

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush_para()
            close_list()
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush_para()
            close_list()
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            numeric = [bool(rows) and all(_is_num(r[k]) for r in rows if k < len(r) and r[k]) for k in range(len(head))]
            out.append("<table><thead><tr>")
            out += [f'<th class="{"n" if numeric[k] else ""}">{_inline(h)}</th>' for k, h in enumerate(head)]
            out.append("</tr></thead><tbody>")
            for r in rows:
                cells = [
                    f'<td class="{"n" if k < len(numeric) and numeric[k] else ""}">{_inline(c)}</td>'
                    for k, c in enumerate(r)
                ]
                out.append("<tr>" + "".join(cells) + "</tr>")
            out.append("</tbody></table>")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            flush_para()
            close_list()
            level = min(len(m.group(1)) + 1, 3)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"^\s*([-*•]|\d+[.)])\s+(.*)", line)
        if m:
            flush_para()
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if lst != kind:
                close_list()
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{_inline(m.group(2))}</li>")
            i += 1
            continue
        close_list()
        para.append(line.strip())
        i += 1
    flush_para()
    close_list()
    return "\n".join(out)


def show_answer(engine, markdown: str, title: str = "", open_it: bool = True) -> Path:
    real_md = engine.restore(markdown or "")
    real_title = engine.restore(title or "") or "Answer"
    now = dt.datetime.now()
    body = markdown_to_html(real_md)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(real_title)}</title><style>{_CSS}</style></head><body><main>"
        '<span class="tag">Real values · only on this computer</span>'
        f"<h1>{html.escape(real_title)}</h1>"
        f'<div class="meta">{now:%d %b %Y, %H:%M} · restored by Doublecast from the AI\'s answer</div>'
        f"{body}</main></body></html>"
    )
    folder = engine.config.home / "answers"
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    slug = re.sub(r"[^\w]+", "-", (title or "answer").lower()).strip("-")[:40] or "answer"
    path = folder / f"{now:%Y%m%d-%H%M%S}-{slug}.html"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(page)
    if open_it:
        _open(path)
    return path


def _open(path: Path) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


CONFIRMATION = (
    "Shown to the user in their browser with the real values (they are not returned to you). "
    "Do not repeat the answer; you can tell them it opened."
)
