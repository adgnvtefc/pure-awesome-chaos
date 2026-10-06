"""gallery/index.html: one card per night, newest first. Open it with your coffee."""

import html
import json
import re
import time
from pathlib import Path

from chaos import config, memory

IMAGE_EXTS = {".png", ".gif", ".jpg", ".jpeg", ".svg", ".webp"}


def build() -> Path:
    nights = []
    for f in sorted(config.NIGHTS.glob("*/night.json"), reverse=True):
        try:
            nights.append((f.parent, json.loads(f.read_text())))
        except json.JSONDecodeError:
            continue
    cards = "\n".join(_card(d, s) for d, s in nights) or '<p class="empty">No nights yet. Tonight\'s the night.</p>'
    lessons = "".join(f"<li>{html.escape(x)}</li>" for x in memory.lessons()) or "<li>Nothing yet.</li>"
    done = [s for _, s in nights if s.get("status") == "done"]
    page = TEMPLATE.format(
        cards=cards,
        lessons=lessons,
        count=f"{len(done)} app" + ("" if len(done) == 1 else "s"),
        tests=sum((s.get("tests") or {}).get("passed", 0) for s in done),
        updated=time.strftime("%Y-%m-%d %H:%M"),
    )
    config.GALLERY.mkdir(parents=True, exist_ok=True)
    out = config.GALLERY / "index.html"
    out.write_text(page)
    return out


def _card(night_dir: Path, s: dict) -> str:
    rel = f"../nights/{night_dir.name}"
    status = s.get("status", "?")
    tests = s.get("tests") or {}
    dice = s.get("dice") or {}
    minutes = ((s.get("ended") or time.time()) - s.get("started", time.time())) / 60
    chips = [
        f'<span class="chip {status}">{html.escape(status)}</span>',
        f'<span class="chip">tests {tests.get("passed", 0)}✓ {tests.get("failed", 0)}✗</span>' if tests else "",
        f'<span class="chip">plan {s.get("plan_done", 0)}/{s.get("plan_total", 0)}</span>',
        f'<span class="chip">{len(s.get("sessions") or [])} sessions · {minutes:.0f} min</span>',
        f'<span class="chip fun">fun {s["fun_rating"]}/10</span>' if s.get("fun_rating") else "",
    ]
    images = _images(night_dir / "app")[:4]
    thumbs = "".join(f'<a href="{rel}/app/{html.escape(i)}"><img src="{rel}/app/{html.escape(i)}" alt="{html.escape(i)}" loading="lazy"></a>' for i in images)
    report_path = night_dir / "REPORT.md"
    report = _markdown(report_path.read_text()) if report_path.exists() else ""
    error = f'<p class="error">{html.escape(s["error"])}</p>' if s.get("error") else ""
    dice_line = " · ".join(html.escape(str(dice[k])) for k in ("theme", "form", "twist", "mood") if k in dice)
    return f"""
<article class="card" id="{html.escape(night_dir.name)}">
  <header>
    <p class="date">{html.escape(s.get("date", ""))}</p>
    <h2>{html.escape(s.get("name") or "(no idea yet)")}</h2>
    <p class="pitch">{html.escape(s.get("pitch", ""))}</p>
    <p class="dice">🎲 {dice_line}</p>
    <div class="chips">{"".join(chips)}</div>
  </header>
  {error}
  {f'<div class="thumbs">{thumbs}</div>' if thumbs else ""}
  {f"<details><summary>Morning report</summary><div class='report'>{report}</div></details>" if report else ""}
  <p class="links"><a href="{rel}/app/">app folder</a> · <a href="{rel}/night.log">night log</a></p>
</article>"""


def _images(app: Path) -> list[str]:
    if not app.is_dir():
        return []
    found = [
        p for p in app.rglob("*")
        if p.suffix.lower() in IMAGE_EXTS and ".git" not in p.parts and ".cache" not in p.parts and _really_is(p)
    ]
    found.sort(key=lambda p: p.stat().st_size, reverse=True)
    return [str(p.relative_to(app)) for p in found]


def _really_is(p: Path) -> bool:
    """Browsers trust the extension for local files: an SVG named .png shows as broken."""
    try:
        head = p.read_bytes()[:512]
    except OSError:
        return False
    ext = p.suffix.lower()
    if ext == ".svg":
        return b"<svg" in head
    signatures = {".png": [b"\x89PNG"], ".jpg": [b"\xff\xd8"], ".jpeg": [b"\xff\xd8"], ".gif": [b"GIF8"], ".webp": [b"RIFF"]}
    return any(head.startswith(sig) for sig in signatures.get(ext, []))


def _markdown(md: str) -> str:
    """Just enough Markdown for a morning report: headings, lists, code, bold, inline code."""
    out, in_code, in_list = [], False, False
    for raw in md.splitlines():
        if raw.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(raw))
            continue
        line = html.escape(raw)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        bullet = re.match(r"^\s*[-*]\s+(.*)", line)
        if bullet and not in_list:
            out.append("<ul>")
            in_list = True
        if not bullet and in_list:
            out.append("</ul>")
            in_list = False
        if bullet:
            out.append(f"<li>{bullet.group(1)}</li>")
        elif m := re.match(r"^(#{1,4})\s+(.*)", line):
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{m.group(2)}</h{level}>")
        elif line.startswith("&gt;"):
            out.append(f"<blockquote>{line[4:].strip()}</blockquote>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out).replace("<pre><code>\n", "<pre><code>").replace("\n</code></pre>", "</code></pre>")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pure Awesome Chaos</title>
<style>
:root {{
  --bg: #faf7f2; --surface: #ffffff; --text: #1d1b19; --muted: #6b655d; --line: #e8e2d8;
  --accent: #e4572e; --good: #2e7d4f; --bad: #b3261e; --chip: #f1ece4; --code: #f4efe7;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #141311; --surface: #1d1b19; --text: #f1ece4; --muted: #a39b90; --line: #2f2c28;
    --accent: #ff7a4d; --good: #6fcf97; --bad: #ff8a80; --chip: #2a2723; --code: #24211e;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #141311; --surface: #1d1b19; --text: #f1ece4; --muted: #a39b90; --line: #2f2c28;
  --accent: #ff7a4d; --good: #6fcf97; --bad: #ff8a80; --chip: #2a2723; --code: #24211e;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width: 860px; margin: 0 auto; padding: 40px 16px 80px; }}
h1 {{ font-size: 2.4rem; margin: 0; letter-spacing: -0.03em; }}
h1 span {{ color: var(--accent); }}
.sub {{ color: var(--muted); margin: 6px 0 32px; }}
.card {{ background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 22px; margin-bottom: 20px; }}
.card h2 {{ margin: 2px 0 6px; font-size: 1.5rem; letter-spacing: -0.02em; }}
.date {{ margin: 0; color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; }}
.pitch {{ margin: 0 0 8px; }}
.dice {{ margin: 0 0 12px; color: var(--muted); font-size: 0.9rem; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.chip {{ background: var(--chip); border-radius: 999px; padding: 2px 10px; font-size: 0.8rem; font-variant-numeric: tabular-nums; }}
.chip.done {{ color: var(--good); }} .chip.failed, .chip.interrupted {{ color: var(--bad); }}
.chip.running {{ color: var(--accent); }} .chip.fun {{ color: var(--accent); }}
.error {{ color: var(--bad); font-size: 0.9rem; }}
.thumbs {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; margin-top: 16px; }}
.thumbs img {{ width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; border: 1px solid var(--line); display: block; }}
details {{ margin-top: 16px; }}
summary {{ cursor: pointer; color: var(--accent); font-weight: 600; }}
.report {{ border-top: 1px solid var(--line); margin-top: 10px; padding-top: 4px; overflow-wrap: anywhere; }}
.report h3, .report h4 {{ margin: 18px 0 6px; }}
pre {{ background: var(--code); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; }}
code {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.9em; }}
blockquote {{ margin: 8px 0; padding-left: 12px; border-left: 3px solid var(--accent); color: var(--muted); }}
.links {{ margin: 14px 0 0; font-size: 0.9rem; }}
a {{ color: var(--accent); }}
.lessons {{ margin-top: 40px; }}
.lessons li {{ margin-bottom: 6px; }}
.empty {{ color: var(--muted); }}
</style>
</head>
<body>
<main>
  <h1>Pure Awesome <span>Chaos</span></h1>
  <p class="sub">{count} built while you slept · {tests} tests passing · updated {updated}</p>
  {cards}
  <section class="lessons">
    <h2>What Chaos has learned</h2>
    <ul>{lessons}</ul>
  </section>
</main>
</body>
</html>
"""
