"""Render docs/demo.gif from real ContextSmith runs.

Every command below is executed for real and its actual output is drawn; nothing is
typed by hand. The only edit: long local paths are shortened for display (repo -> ~/flask). Usage: python docs/demo/make_demo.py /path/to/a/flask/checkout
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS = 96, 30
FONT_SIZE = 15
PAD = 18
BG, FG, DIM = (13, 17, 23), (201, 209, 217), (125, 133, 144)
GREEN, BLUE, YELLOW = (63, 185, 80), (88, 166, 255), (210, 153, 34)
OUT = Path(__file__).resolve().parents[1] / "demo.gif"

SCENES = [
    ("# Index a repository: code graph, BM25, git history and local embeddings", None),
    ("ctxsmith index .", None),
    ("# Which files matter for this bug report? Each signal says how it found the file.", None),
    ('ctxsmith rank "Raise an error when a blueprint name contains a dot" -n 5', None),
    ("# The best context for the task, packed to a hard token budget", None),
    ('ctxsmith context "Raise an error when a blueprint name contains a dot" -b 4000', 24),
    ("# What could break if this function changes?", None),
    ("ctxsmith impact url_for -n 6", None),
    ("# Plug it into Claude Code (or Cursor, Codex, Windsurf) over MCP", None),
    ("ctxsmith mcp-config claude", None),
]


def _font() -> ImageFont.FreeTypeFont:
    for name in ("CascadiaMono.ttf", "consola.ttf", "DejaVuSansMono.ttf", "Menlo.ttc"):
        try:
            return ImageFont.truetype(name, FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def run(cmd: str, cwd: Path, max_lines: int | None) -> list[str]:
    path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])  # this venv's ctxsmith
    env = {**os.environ, "PATH": path, "COLUMNS": str(COLS), "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8",
           "HF_HUB_DISABLE_PROGRESS_BARS": "1", "PYTHONWARNINGS": "ignore"}
    out = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env)
    text = re.sub(r"\x1b\[[0-9;]*m", "", out.stdout + out.stderr)
    for long, short in ((str(cwd.resolve()), "~/flask"), (str(Path.home()), "~")):
        text = text.replace(long, short)
    lines = [ln[i : i + COLS] for ln in text.rstrip().splitlines() for i in range(0, max(len(ln), 1), COLS)]
    lines = [ln for ln in lines if "UserWarning" not in ln and "warnings.warn" not in ln]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines] + ["…"]
    return lines


class Terminal:
    def __init__(self) -> None:
        self.font = _font()
        box = self.font.getbbox("M")
        self.cw, self.ch = box[2] - box[0], int(FONT_SIZE * 1.45)
        self.size = (COLS * self.cw + 2 * PAD, ROWS * self.ch + 2 * PAD + 26)
        self.lines: list[tuple[str, tuple]] = []
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []

    def frame(self, ms: int) -> None:
        img = Image.new("RGB", self.size, BG)
        d = ImageDraw.Draw(img)
        for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse((PAD + i * 20, 9, PAD + i * 20 + 11, 20), fill=c)
        d.text((self.size[0] // 2 - 70, 6), "contextsmith demo", font=self.font, fill=DIM)
        for row, (text, color) in enumerate(self.lines[-ROWS:]):
            y = PAD + 26 + row * self.ch
            if text.startswith("$ "):
                d.text((PAD, y), "$", font=self.font, fill=GREEN)
                d.text((PAD + 2 * self.cw, y), text[2:], font=self.font, fill=color)
            else:
                d.text((PAD, y), text, font=self.font, fill=color)
        self.frames.append(img)
        self.durations.append(ms)

    def type(self, cmd: str) -> None:
        comment = cmd.startswith("#")
        color = DIM if comment else FG
        text = cmd if comment else "$ " + cmd
        step = 4 if comment else 2
        self.lines.append(("", color))
        for i in range(step, len(text) + step, step):
            self.lines[-1] = (text[:i], color)
            self.frame(35)
        self.frame(500 if comment else 350)

    def show(self, lines: list[str]) -> None:
        for i in range(0, len(lines), 3):
            for ln in lines[i : i + 3]:
                color = BLUE if ln.startswith("#") else YELLOW if ln.startswith(("Indexed", "claude mcp")) else FG
                self.lines.append((ln, color))
            self.frame(60)
        self.frame(1800 + 40 * len(lines))

    def save(self) -> None:
        palette = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT) for f in self.frames]
        palette[0].save(OUT, save_all=True, append_images=palette[1:], duration=self.durations,
                        loop=0, optimize=True, disposal=1)


def main(repo: Path) -> None:
    term = Terminal()
    for cmd, max_lines in SCENES:
        term.type(cmd)
        if not cmd.startswith("#"):
            term.show(run(cmd, repo, max_lines))
            term.lines.append(("", FG))
    term.frame(3000)
    term.save()
    total = sum(term.durations) / 1000
    print(f"wrote {OUT} · {len(term.frames)} frames · {total:.0f}s · {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
