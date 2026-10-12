"""Live parallel MCP renewal check using a temporary invalid session and one real login."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile

from mcp import Client, StdioServerParameters


async def main():
    with tempfile.TemporaryDirectory() as directory:
        session = Path(directory) / "session.json"
        attempts = Path(directory) / "attempts"
        session.write_text(json.dumps({"cookie": "laravel_token=concurrency-test-invalid", "csrf": "expired"}))
        session.chmod(0o600)
        bootstrap = '''
from pathlib import Path
import sys
import threading
import clearancejobs as cj
import clearancejobs_auth as auth
import clearancejobs_mcp as server
path, attempts = map(Path, sys.argv[1:])
cj.saved_jobs.__kwdefaults__["session_file"] = path
cj.applications.__kwdefaults__["session_file"] = path
original_renew = cj._renew_session
barrier = threading.Barrier(2)
def simultaneous_renew(*args):
    barrier.wait(timeout=15)
    return original_renew(*args)
cj._renew_session = simultaneous_renew
original_login = auth._login
def counted_login(file):
    with attempts.open("a") as stream:
        stream.write("login\\n")
    return original_login(file)
auth._login = counted_login
server.mcp.run()
'''
        parameters = StdioServerParameters(command=sys.executable,
            args=["-c", bootstrap, str(session), str(attempts)],
            cwd=str(Path(__file__).resolve().parent))
        async with Client(parameters, read_timeout_seconds=75) as client:
            results = await asyncio.gather(*(client.call_tool(name, {})
                for name in ("get_saved_jobs", "get_applications")))
            for name, result in zip(("get_saved_jobs", "get_applications"), results):
                assert not result.is_error, result.content
                print(f"{name}: OK; {len(result.structured_content['jobs'])} entries")
        assert attempts.read_text().splitlines() == ["login"]
        assert session.stat().st_mode & 0o777 == 0o600
        print("Parallel expired MCP requests: OK; 1 login; 2 successful retries; session mode 0600")


if __name__ == "__main__":
    asyncio.run(main())
