"""Record the real outputs shown in the demo video.

Usage: python docs/demo/capture.py /path/to/flask out.json
Runs the CLI on a fresh index and calls the MCP server over stdio, exactly as an agent
would. make_video.py draws only what this file recorded.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TASK = "Raise an error when a blueprint name contains a dot"
BIN = Path(sys.executable).parent


def cli(repo: Path, *args: str) -> str:
    env = {**os.environ, "COLUMNS": "100", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONWARNINGS": "ignore", "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
    out = subprocess.run([str(BIN / "ctxsmith"), *args], cwd=repo, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env)
    return re.sub(r"\x1b\[[0-9;]*m", "", out.stdout + out.stderr).rstrip()


async def mcp_calls(repo: Path) -> list[dict]:
    params = StdioServerParameters(command=str(BIN / "contextsmith"), args=[],
                                   env={**os.environ, "CTXSMITH_ROOT": str(repo), "PYTHONWARNINGS": "ignore"})
    calls = [("get_context", {"task": TASK, "budget_tokens": 2000}), ("impact", {"name": "url_for"})]
    out = []
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = [t.name for t in (await session.list_tools()).tools]
        for name, args in calls:
            res = await session.call_tool(name, args)
            out.append({"tool": name, "args": args, "result": res.content[0].text})
    return [{"tools": tools}, *out]


def main(repo: Path, dest: Path) -> None:
    shutil.rmtree(repo / ".contextsmith", ignore_errors=True)
    record = {
        "index": cli(repo, "index", "."),
        "context": cli(repo, "context", TASK, "-b", "4000"),
        "mcp": asyncio.run(mcp_calls(repo)),
    }
    dest.write_text(json.dumps(record, indent=1), encoding="utf-8")
    print(f"recorded to {dest}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]))
