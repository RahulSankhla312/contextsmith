"""Render docs/contextsmith-demo.mp4 (60 s, 1080p, captioned for muted autoplay).

Usage: python docs/demo/make_video.py capture.json [out.mp4]
Every terminal and MCP frame is drawn from capture.json, recorded by capture.py from real
runs; the chart uses the published Django results (bench/results-django/summary.md).
Needs Pillow and imageio-ffmpeg (dev-only; not dependencies of the package).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
BG, PANEL, BORDER = (13, 17, 23), (22, 27, 34), (48, 54, 61)
TEXT, MUTED, DIM = (230, 237, 243), (139, 148, 158), (96, 104, 114)
GREEN, CODEBLUE, HIGHLIGHT = (63, 185, 80), (88, 166, 255), (71, 56, 14)
BASELINE, OURS = (57, 135, 229), (217, 89, 38)  # validated categorical pair on this surface
OUT = Path(__file__).resolve().parents[1] / "contextsmith-demo.mp4"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (name, "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


F = {
    "hero": font("segoeuib.ttf", 112), "h1": font("segoeuib.ttf", 64), "h2": font("segoeuib.ttf", 46),
    "body": font("segoeui.ttf", 38), "bodyb": font("segoeuib.ttf", 38), "small": font("segoeui.ttf", 28),
    "cap": font("segoeui.ttf", 34), "stat": font("segoeuib.ttf", 170), "mono": font("CascadiaMono.ttf", 25),
    "monob": font("CascadiaMono.ttf", 34), "label": font("segoeuib.ttf", 30),
}


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def appear(t: float, start: float, dur: float = 0.45) -> float:
    return ease((t - start) / dur)


def mix(c: tuple, a: float, base: tuple = BG) -> tuple:
    return tuple(int(base[i] + (c[i] - base[i]) * a) for i in range(3))


class Canvas:
    def __init__(self) -> None:
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)

    def text(self, xy, s, f, color=TEXT, a=1.0, anchor="la"):
        if a > 0:
            self.d.text(xy, s, font=F[f], fill=mix(color, a), anchor=anchor)

    def width(self, s, f) -> float:
        return F[f].getlength(s)

    def box(self, xy, fill=PANEL, outline=BORDER, r=18, a=1.0, width=2):
        self.d.rounded_rectangle(xy, r, fill=mix(fill, a), outline=mix(outline, a) if outline else None, width=width)

    def window(self, x0, y0, x1, y1, title, a=1.0):
        self.box((x0, y0, x1, y1), a=a)
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            cx = x0 + 28 + i * 26
            self.d.ellipse((cx - 8, y0 + 22 - 8, cx + 8, y0 + 22 + 8), fill=mix(c, a))
        self.text(((x0 + x1) / 2, y0 + 22), title, "small", MUTED, a, anchor="mm")
        self.d.line((x0, y0 + 44, x1, y0 + 44), fill=mix(BORDER, a), width=2)

    def caption(self, s, a=1.0):
        if not s:
            return
        w = self.width(s, "cap") + 64
        self.box(((W - w) / 2, H - 112, (W + w) / 2, H - 48), fill=(28, 33, 40), outline=None, r=14, a=a)
        self.text((W / 2, H - 80), s, "cap", TEXT, a, anchor="mm")

    def step(self, n, title, a=1.0):
        self.d.ellipse((120, 58, 176, 114), fill=mix(OURS, a))
        self.text((148, 86), str(n), "label", (255, 255, 255), a, anchor="mm")
        self.text((200, 86), title, "h2", TEXT, a, anchor="lm")


# --------------------------------------------------------------------------- scenes


def scene_title(c: Canvas, t: float, dur: float, rec: dict) -> None:
    a = appear(t, 0.1, 0.8)
    rise = (1 - a) * 40
    c.text((W / 2, 400 + rise), "ContextSmith", "hero", TEXT, a, anchor="mm")
    b = appear(t, 0.7)
    c.text((W / 2, 530), "Give your coding agent the right code, not more code.", "h2", OURS, b, anchor="mm")
    c.text((W / 2, 640), "Open source  ·  Runs locally  ·  Works over MCP  ·  MIT", "body", MUTED, appear(t, 1.4), anchor="mm")
    c.caption("A context engine for Claude Code, Cursor, Codex and any MCP agent", appear(t, 2.0))


def scene_problem(c: Canvas, t: float, dur: float, rec: dict) -> None:
    c.text((160, 260), "Coding agents read the wrong code.", "h1", TEXT, appear(t, 0.1))
    points = ["They grep and open whole files.", "The context window fills up fast.",
              "The function that needs the fix often never makes it in."]
    for i, p in enumerate(points):
        a = appear(t, 0.8 + 0.7 * i)
        c.d.ellipse((168, 406 + i * 92, 184, 422 + i * 92), fill=mix(MUTED, a))
        c.text((210, 414 + i * 92), p, "body", TEXT, a, anchor="lm")
    a = appear(t, 2.9, 0.6)
    c.box((1260, 390, 1800, 810), a=a)
    c.text((1530, 555), "29%", "stat", BASELINE, a, anchor="mm")
    for i, line in enumerate(["of real bug fixes had the right file", "inside a 4,000-token context, using", "search + whole files"]):
        c.text((1530, 675 + i * 44), line, "small", TEXT if i < 2 else MUTED, a, anchor="mm")
    c.caption("114 Django issues from SWE-bench Lite, never used for tuning", appear(t, 3.4))


def _terminal_lines(rec: dict) -> list[tuple[float, str, str]]:
    """(time, kind, text) events for the CLI scene."""
    ctx = rec["context"].splitlines()
    dot = next(i for i, ln in enumerate(ctx) if '"." in name' in ln)
    shown = ctx[:11] + ctx[12 : dot + 3] + ["…"] + [ln for ln in ctx if "tokens ·" in ln][-1:]
    events = [(0.3, "cmd", "ctxsmith index .")]
    t = 1.5
    for ln in rec["index"].splitlines():
        events.append((t, "out", ln))
        t += 0.25
    events.append((t + 1.1, "cmd", 'ctxsmith context "Raise an error when a blueprint name contains a dot" -b 4000'))
    t += 3.6
    for ln in shown:
        events.append((t, "out", ln))
        t += 0.13
    return events


def scene_cli(c: Canvas, t: float, dur: float, rec: dict) -> None:
    c.step(1, "Index any repository, ask for the best context", appear(t, 0.0))
    x0, y0, x1, y1 = 120, 150, 1800, 940
    c.window(x0, y0, x1, y1, "terminal  ·  pallets/flask")
    rows, lh = 19, 36
    lines: list[tuple[str, str]] = []
    for at, kind, s in _terminal_lines(rec):
        if t < at:
            break
        if kind == "cmd":
            n = int((t - at) / 0.03)
            lines.append(("cmd", s[:n]))
        else:
            lines.append(("out", s))
    for i, (kind, s) in enumerate(lines[-rows:]):
        y = y0 + 70 + i * lh
        if kind == "cmd":
            c.text((x0 + 30, y), "$", "mono", GREEN)
            c.text((x0 + 60, y), s, "mono", TEXT)
            continue
        hot = '"." in name' in s or "may not contain a dot" in s
        if hot:
            c.d.rectangle((x0 + 20, y - 4, x1 - 20, y + lh - 6), fill=HIGHLIGHT)
        color = CODEBLUE if s.startswith(("#", "##")) else OURS if s.startswith("Indexed") or "tokens ·" in s else TEXT
        c.text((x0 + 30, y), s[:104], "mono", color)
    cap = "Hybrid search over a code graph, embeddings and git history"
    if t > 6.5:
        cap = "The pack leads with Blueprint.__init__, where the dot check lives"
    c.caption(cap, appear(t, 1.0))


def scene_mcp(c: Canvas, t: float, dur: float, rec: dict) -> None:
    c.step(2, "Your agent calls it over MCP", appear(t, 0.0))
    setup = "claude mcp add contextsmith -- ctxsmith serve --path ."
    a = appear(t, 0.2)
    c.box((120, 150, 1800, 230), a=a)
    c.text((150, 190), "$", "monob", GREEN, a, anchor="lm")
    c.text((190, 190), setup[: int(max(t - 0.4, 0) / 0.025)], "monob", TEXT, a, anchor="lm")
    tools = rec["mcp"][0]["tools"]
    c.text((120, 262), f"{len(tools)} tools: " + ", ".join(tools), "small", MUTED, appear(t, 1.8))

    calls = rec["mcp"][1:]
    blocks = [
        (2.6, calls[0], lambda r: r.splitlines()[:6] + ["…"] + r.splitlines()[-1:]),
        (8.6, calls[1], lambda r: r.splitlines()[:5]),
    ]
    y = 320
    for start, call, pick in blocks:
        a = appear(t, start)
        if a <= 0:
            break
        args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
        c.text((120, y), "agent  →", "label", OURS, a)
        c.text((270, y + 2), f"{call['tool']}({args})", "mono", TEXT, a)
        body = pick(call["result"])
        b = appear(t, start + 0.8)
        top = y + 50
        c.box((120, top, 1800, top + 24 + 34 * len(body)), a=b)
        for i, ln in enumerate(body):
            color = OURS if ln.startswith("<!--") or "callers in" in ln else CODEBLUE if ln.startswith("#") else TEXT
            c.text((150, top + 14 + i * 34), ln[:110], "mono", color, b)
        y = top + 24 + 34 * len(body) + 40
    cap = "Real calls over stdio: the same protocol Claude Code, Cursor and Codex use"
    if t > 9.0:
        cap = "Before a change: everything that calls url_for, nearest first"
    c.caption(cap, appear(t, 1.2))


METRICS = [  # (label, baseline %, ContextSmith %) from bench/results-django/summary.md
    ("Fix's file in the top 5 results", 77.2, 85.1),
    ("Fix's file inside a 4,000-token context", 28.9, 92.1),
    ("Exact lines the fix changes, shown in 4,000 tokens", 28.9, 48.1),
]


def scene_chart(c: Canvas, t: float, dur: float, rec: dict) -> None:
    c.text((120, 70), "Measured, not claimed", "h1", TEXT, appear(t, 0.0))
    c.text((120, 160), "114 Django issues from SWE-bench Lite, held out from all tuning", "body", MUTED, appear(t, 0.3))
    la = appear(t, 0.5)
    for i, (name, color) in enumerate((("Search + whole files", BASELINE), ("ContextSmith", OURS))):
        x = 120 + i * 380
        c.d.rounded_rectangle((x, 236, x + 28, 264), 4, fill=mix(color, la))
        c.text((x + 42, 250), name, "small", TEXT, la, anchor="lm")
    x0, x1 = 120, 1560
    span = x1 - x0
    for g, (label, base, ours) in enumerate(METRICS):
        y = 320 + g * 210
        start = 0.9 + g * 0.7
        c.text((x0, y), label, "bodyb", TEXT, appear(t, start - 0.3))
        for k, (val, color) in enumerate(((base, BASELINE), (ours, OURS))):
            grow = ease((t - start - 0.15 * k) / 1.2)
            if grow <= 0:
                continue
            by = y + 60 + k * 58
            right = x0 + span * val / 100 * grow
            c.d.rounded_rectangle((x0, by, max(right, x0 + 8), by + 48), 4, fill=color)
            v = appear(t, start + 1.2 + 0.15 * k)
            c.text((right + 18, by + 24), f"{val:.0f}%", "label", TEXT, v, anchor="lm")
        if g == 1:
            c.text((1700, y + 112), "3.2x", "h1", OURS, appear(t, start + 1.6), anchor="mm")
        if g == 2:
            c.text((1700, y + 112), "1.7x", "h1", OURS, appear(t, start + 1.6), anchor="mm")
    c.caption("Same token budget. The right code makes it in far more often.", appear(t, 3.6))


def scene_cta(c: Canvas, t: float, dur: float, rec: dict) -> None:
    c.text((W / 2, 330), "Try it in a minute", "h1", TEXT, appear(t, 0.0), anchor="mm")
    a = appear(t, 0.4)
    cmd = 'pip install "contextsmith[semantic]"'
    w = c.width(cmd, "monob") + 120
    c.box(((W - w) / 2, 420, (W + w) / 2, 520), a=a)
    c.text((W / 2, 470), cmd, "monob", TEXT, a, anchor="mm")
    c.text((W / 2, 620), "github.com/RahulSankhla312/contextsmith", "h2", OURS, appear(t, 0.9), anchor="mm")
    c.text((W / 2, 710), "Local  ·  No API keys  ·  MIT  ·  On PyPI and the official MCP Registry", "body", MUTED,
           appear(t, 1.3), anchor="mm")
    c.caption("Star it, try it on your repo, tell me what it gets wrong", appear(t, 1.8))


SCENES = [(scene_title, 5.0), (scene_problem, 6.5), (scene_cli, 16.5), (scene_mcp, 15.0),
          (scene_chart, 11.0), (scene_cta, 6.0)]


def frames(rec: dict):
    fade = 0.35
    for fn, dur in SCENES:
        for i in range(int(dur * FPS)):
            t = i / FPS
            c = Canvas()
            fn(c, t, dur, rec)
            a = min(1.0, t / fade, (dur - t) / fade)
            img = c.img if a >= 1 else Image.blend(Image.new("RGB", (W, H), BG), c.img, max(a, 0.0))
            yield img


def main(capture: Path, out: Path) -> None:
    rec = json.loads(capture.read_text(encoding="utf-8"))
    writer = imageio_ffmpeg.write_frames(str(out), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p", macro_block_size=1,
                                         output_params=["-crf", "20", "-preset", "medium", "-movflags", "+faststart"])
    writer.send(None)
    n = 0
    for img in frames(rec):
        writer.send(img.tobytes())
        n += 1
    writer.close()
    secs = n / FPS
    print(f"wrote {out} · {n} frames · {secs:.0f}s · {out.stat().st_size / 1e6:.1f} MB · {math.ceil(secs)}s")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else OUT)
