"""Live stdio protocol check; performs four read-only requests without dumping account data."""

import asyncio
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters


async def main():
    root = Path(__file__).resolve().parent
    server = StdioServerParameters(command=sys.executable, args=[str(root / "server.py")])
    async with Client(server, read_timeout_seconds=40) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "search_jobs", "get_saved_jobs", "get_applications", "get_job_details",
        }
        assert all(tool.annotations.read_only_hint for tool in tools)
        print(f"MCP handshake: OK; {len(tools)} read-only tools")
        search = await client.call_tool("search_jobs", {"keywords": "devsecops", "state": "FL", "limit": 2})
        assert not search.is_error, search.content
        assert search.structured_content["jobs"], "Expected at least one live DevSecOps match"
        print("search_jobs (FL):", len(search.structured_content["jobs"]), "entries")
        for name in ("get_saved_jobs", "get_applications"):
            result = await client.call_tool(name, {})
            assert not result.is_error, result.content
            assert isinstance(result.structured_content["jobs"], list)
            assert "pagination" in result.structured_content
            print(f"{name}:", len(result.structured_content["jobs"]), "entries; total:",
                  result.structured_content["pagination"]["total"])
        job_id = search.structured_content["jobs"][0]["job_id"]
        details = await client.call_tool("get_job_details", {"job_id": job_id})
        assert not details.is_error, details.content
        assert details.structured_content["job_id"] == job_id
        assert details.structured_content["description"], "Description must not be empty"
        print("get_job_details:", len(details.structured_content["description"]), "characters")


if __name__ == "__main__":
    asyncio.run(main())
