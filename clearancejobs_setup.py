"""Print portable MCP configuration or register this installation with Codex."""

import argparse
import json
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", action="store_true", help="Register with Codex; changes its local MCP configuration")
    args = parser.parse_args()
    command = [sys.executable, "-m", "clearancejobs_mcp"]
    if args.codex:
        codex = shutil.which("codex")
        if codex is None:
            parser.exit(1, "Codex CLI not found. Run clearancejobs-setup for generic MCP configuration.\n")
        result = subprocess.run([codex, "mcp", "add", "clearancejobs", "--", *command], check=False)
        if result.returncode == 0:
            print("ClearanceJobs registered. Restart Codex to load the tools.")
        return result.returncode
    print(json.dumps({"mcpServers": {"clearancejobs": {"command": command[0], "args": command[1:]}}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
