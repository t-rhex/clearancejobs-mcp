"""Inspect local beta archives, install a wheel cleanly, and check offline stdio setup."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile

from mcp import Client, StdioServerParameters

MODULES = {"clearancejobs.py", "clearancejobs_auth.py", "clearancejobs_mcp.py", "clearancejobs_setup.py"}
SOURCE_FILES = MODULES | {"pyproject.toml", "README.md", "JOB_SEARCH.md", "BETA_NOTICE.md", ".python-version",
    "uv.lock", "MANIFEST.in", "server.py", "test_clearancejobs.py", "test_auth.py", "test_server.py",
    "test_setup.py", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", "examples/search.py", "check_mcp.py", "check_auth_concurrency.py", "check_beta.py", "PKG-INFO", "setup.cfg"}


def inspect_archives(wheel, source):
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    with tarfile.open(source) as archive:
        source_files = {member.name.split("/", 1)[1]: archive.extractfile(member).read()
                        for member in archive.getmembers() if member.isfile()}
    for name in wheel_files:
        assert name in MODULES or name.startswith("clearancejobs_mcp-0.1.0b1.dist-info/"), name
    for name in source_files:
        assert name in SOURCE_FILES or name == "clearancejobs_mcp.egg-info/SOURCES.txt" or (name.startswith("docs/images/") and name.endswith(".png")), name
    assert MODULES <= wheel_files.keys()
    for name, body in (wheel_files | source_files).items():
        if name.endswith(".png"):
            continue
        text = body.decode("utf-8")
        assert str(Path.home()) not in text, f"Local home path in {name}"
        assert not any(marker in text for marker in ("/" + "Users/", "file:" + "///")), f"Machine path in {name}"
    print(f"Archive allowlist/privacy check: OK; {len(wheel_files)} wheel files; {len(source_files)} source files")


async def main():
    root = Path(__file__).resolve().parent
    wheel = root / "dist/clearancejobs_mcp-0.1.0b1-py3-none-any.whl"
    source = root / "dist/clearancejobs_mcp-0.1.0b1.tar.gz"
    inspect_archives(wheel, source)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        environment = temporary / "venv"
        subprocess.run(["uv", "venv", "--python", "3.13", str(environment)], check=True, capture_output=True)
        python = environment / "bin/python"
        subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True, capture_output=True)
        clean = os.environ.copy()
        clean.pop("PYTHONPATH", None)
        clean["HOME"] = str(temporary / "home")
        Path(clean["HOME"]).mkdir()
        clean["XDG_CONFIG_HOME"] = str(temporary / "config")
        for command in ("clearancejobs", "clearancejobs-auth", "clearancejobs-mcp", "clearancejobs-setup"):
            # The stdio server is checked through its protocol below, not --help.
            if command != "clearancejobs-mcp":
                result = subprocess.run([str(environment / "bin" / command), "--help"],
                    check=True, capture_output=True, text=True, env=clean, cwd=temporary)
                assert "usage:" in result.stdout
        result = subprocess.run([str(environment / "bin/clearancejobs-setup")],
            check=True, capture_output=True, text=True, env=clean, cwd=temporary)
        config = json.loads(result.stdout)["mcpServers"]["clearancejobs"]
        assert config == {"command": str(python), "args": ["-m", "clearancejobs_mcp"]}
        parameters = StdioServerParameters(command=config["command"], args=config["args"],
                                           cwd=str(temporary), env=clean)
        async with Client(parameters, read_timeout_seconds=20) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {"search_jobs", "get_saved_jobs", "get_applications", "get_job_details"}
        print("Clean wheel install: OK; installed CLI help and portable MCP config")
        print("Clean-home stdio handshake: OK; 4 tools; no account or Keychain access")


if __name__ == "__main__":
    asyncio.run(main())
