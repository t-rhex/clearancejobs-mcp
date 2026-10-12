"""Local Keychain enrollment and normal ClearanceJobs login. Never expose secrets via MCP."""

import argparse
import ctypes
import fcntl
from getpass import getpass
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener

SERVICE = b"clearancejobs-mcp"
ACCOUNT = b"login"
_FORCE_LOGIN = object()


def _keychain(action, value=None):
    if sys.platform != "darwin":
        raise RuntimeError("Keychain login requires macOS")
    security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    pointer = ctypes.c_void_p
    uint = ctypes.c_uint32
    security.SecKeychainFindGenericPassword.argtypes = [pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p, ctypes.POINTER(uint), ctypes.POINTER(pointer), ctypes.POINTER(pointer)]
    security.SecKeychainAddGenericPassword.argtypes = [pointer, uint, ctypes.c_char_p, uint, ctypes.c_char_p, uint, ctypes.c_char_p, ctypes.POINTER(pointer)]
    security.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, uint, ctypes.c_char_p]
    security.SecKeychainItemDelete.argtypes = [pointer]
    security.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
    core.CFRelease.argtypes = [pointer]
    length, data, item = uint(), pointer(), pointer()
    status = security.SecKeychainFindGenericPassword(None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT, ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
    try:
        if status == -25300:
            if action == "delete":
                return
            if action == "get":
                raise RuntimeError("No ClearanceJobs login in Keychain; run: clearancejobs-auth setup")
            encoded = value.encode()
            status = security.SecKeychainAddGenericPassword(None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT, len(encoded), encoded, None)
        elif status == 0:
            if action == "get":
                return ctypes.string_at(data, length.value).decode()
            if action == "delete":
                status = security.SecKeychainItemDelete(item)
            else:
                encoded = value.encode()
                status = security.SecKeychainItemModifyAttributesAndData(item, None, len(encoded), encoded)
        if status:
            raise RuntimeError(f"macOS Keychain access failed (status {status}); unlock Keychain or allow this Python interpreter")
    finally:
        if data:
            security.SecKeychainItemFreeContent(None, data)
        if item:
            core.CFRelease(item)


def _write_session(path, session):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".session-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(session, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def renew_session(session_file, *, expired_session=_FORCE_LOGIN):
    from clearancejobs import _load_session

    path = Path(session_file)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if expired_session is not _FORCE_LOGIN:
            try:
                current = _load_session(path)
            except FileNotFoundError:
                current = None
            except (OSError, KeyError, TypeError, ValueError):
                raise RuntimeError("Cannot renew an unsafe or malformed session file") from None
            # Another thread or process may already have replaced the failed session.
            if current is not None and current != expired_session:
                return
        _login(session_file)


def _login(session_file):
    from clearancejobs import BASE_URL, HEADERS, _NoRedirect

    try:
        credentials = json.loads(_keychain("get"))
        username, password = credentials["username"], credentials["password"]
        if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Invalid Keychain login; run: clearancejobs-auth setup") from None
    jar = CookieJar()
    opener = build_opener(_NoRedirect(), HTTPCookieProcessor(jar))
    try:
        headers = HEADERS.copy()
        headers.update({"Origin": BASE_URL, "Referer": BASE_URL + "/login"})
        request = Request(BASE_URL + "/api/v1/auth/login", headers=headers,
                          data=json.dumps({"username": username, "password": password}).encode())
        with opener.open(request, timeout=30) as response:
            result = json.loads(response.read())
    except (ValueError, UnicodeError):
        raise RuntimeError("Login returned an invalid response; no further login attempts") from None
    except HTTPError as exc:
        raise RuntimeError(f"Automatic login stopped (HTTP {exc.code}); sign in in the browser if verification is needed, or update Keychain credentials. No further login attempts.") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Could not connect during automatic login; no further login attempts") from None
    token = next((cookie.value for cookie in jar if cookie.name == "laravel_token"
                  and cookie.domain.lstrip(".") in ("clearancejobs.com", "www.clearancejobs.com")
                  and cookie.path == "/"), None)
    csrf = result.get("csrf_token") if isinstance(result, dict) else None
    member = result.get("member") if isinstance(result, dict) else None
    if (not isinstance(member, dict) or not isinstance(csrf, str) or not csrf
            or not token or any(c in csrf + token for c in "\r\n")):
        raise RuntimeError("Login did not provide a complete session; complete verification in the browser. No further login attempts.")
    mfa = member.get("mfa", {})
    if isinstance(mfa, dict) and mfa.get("forced") and not mfa.get("active"):
        raise RuntimeError("Complete required MFA enrollment in the browser; automatic login stopped")
    session = {"cookie": f"laravel_token={token}; laravel_csrf_token={quote(csrf, safe='')}",
               "csrf": csrf}
    _write_session(session_file, session)


def main():
    from clearancejobs import BASE_URL, SESSION_FILE, _listing

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "login", "forget"))
    args = parser.parse_args()
    try:
        if args.action == "setup":
            if not sys.stdin.isatty():
                raise RuntimeError("Run setup in an interactive terminal; never pass credentials as arguments")
            username = input("ClearanceJobs username/email: ").strip()
            password = getpass("ClearanceJobs password (saved in macOS Keychain): ")
            if not username or not password:
                raise RuntimeError("Username and password are required")
            _keychain("set", json.dumps({"username": username, "password": password}))
            print("Login saved in macOS Keychain. Testing normal login...")
        if args.action == "forget":
            _keychain("delete")
            print("Keychain login removed. The existing session file was not revoked or deleted.")
            return 0
        renew_session(SESSION_FILE)
        result = _listing(BASE_URL + "/api/v1/jobs/applications?page=1", session_file=SESSION_FILE, _renew=False)
        print(f"Login verified; applications accessible: {result['meta']['pagination']['total']}")
        return 0
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
