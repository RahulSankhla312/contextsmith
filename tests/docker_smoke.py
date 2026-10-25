"""CI check for the Docker image: the server starts and answers MCP introspection.

Usage: python tests/docker_smoke.py <image>   (needs the `mcp` package and Docker)
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED = {"get_context", "search", "find_symbol", "callers", "callees", "impact",
            "related_files", "add_note", "overview", "reindex"}


async def main(image: str) -> None:
    params = StdioServerParameters(command="docker", args=["run", "-i", "--rm", image])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
    missing = EXPECTED - tools
    if missing:
        raise SystemExit(f"missing tools: {sorted(missing)}")
    print(f"ok: {len(tools)} tools")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
