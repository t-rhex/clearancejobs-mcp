from concurrent.futures import ThreadPoolExecutor
import threading
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import clearancejobs
import clearancejobs_auth as auth


class AuthTests(unittest.TestCase):
    def session(self, path):
        path.write_text(json.dumps({"cookie": "laravel_token=expired", "csrf": "old"}))
        path.chmod(0o600)

    @patch("clearancejobs._renew_session")
    @patch("clearancejobs.build_opener")
    def test_expired_session_renews_once_then_retries(self, opener, renew):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            self.session(path)
            opener.return_value.open.side_effect = [
                HTTPError("", 401, "expired", {}, None),
                io.BytesIO(b'{"data":[],"meta":{"pagination":{}}}'),
            ]
            clearancejobs.applications(session_file=path)
            renew.assert_called_once_with(path, json.loads(path.read_text()))
            self.assertEqual(opener.return_value.open.call_count, 2)

    @patch("clearancejobs._renew_session")
    @patch("clearancejobs.build_opener")
    def test_retry_is_bounded_and_non_auth_errors_do_not_login(self, opener, renew):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            self.session(path)
            for code in (401, 419, 403, 429, 500):
                opener.reset_mock()
                renew.reset_mock()
                opener.return_value.open.side_effect = HTTPError("", code, "error", {}, None)
                with self.assertRaisesRegex(RuntimeError, f"HTTP {code}"):
                    clearancejobs.applications(session_file=path)
                self.assertEqual(renew.call_count, 1 if code in (401, 419) else 0)
                self.assertEqual(opener.return_value.open.call_count, 2 if code in (401, 419) else 1)

    @patch("clearancejobs._renew_session")
    def test_missing_session_can_be_recovered(self, renew):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            with self.assertRaisesRegex(RuntimeError, "missing after login"):
                clearancejobs.applications(session_file=path)
            renew.assert_called_once_with(path, None)

    @patch("clearancejobs._renew_session")
    def test_credentials_cannot_be_sent_to_other_hosts(self, renew):
        with self.assertRaises(ValueError):
            clearancejobs._request("https://evil.example/", session_file="unused")
        renew.assert_not_called()

    @patch("clearancejobs_auth._login")
    @patch("clearancejobs.build_opener")
    def test_parallel_expired_requests_share_one_login(self, opener, login):
        barrier = threading.Barrier(2)
        def respond(request, **kwargs):
            if request.get_header("Cookie") == "laravel_token=expired":
                barrier.wait(timeout=5)
                raise HTTPError("", 401, "expired", {}, None)
            return io.BytesIO(b'{"data":[],"meta":{"pagination":{}}}')
        opener.return_value.open.side_effect = respond
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            self.session(path)
            login.side_effect = lambda file: auth._write_session(file, {"cookie": "fresh", "csrf": "new"})
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(getter, session_file=path)
                           for getter in (clearancejobs.applications, clearancejobs.saved_jobs)]
                for future in futures:
                    self.assertEqual(future.result(timeout=10)["data"], [])
            login.assert_called_once_with(path)
            self.assertEqual(opener.return_value.open.call_count, 4)

    @patch("clearancejobs_auth._login")
    def test_missing_session_waiters_reuse_login_and_bad_files_stay_rejected(self, login):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            login.side_effect = lambda file: auth._write_session(file, {"cookie": "fresh", "csrf": "new"})
            auth.renew_session(path, expired_session=None)
            auth.renew_session(path, expired_session=None)
            self.assertEqual(login.call_count, 1)
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "unsafe or malformed"):
                auth.renew_session(path, expired_session=None)
            self.assertEqual(login.call_count, 1)

    @patch("clearancejobs_auth._keychain", return_value='{"username":"test-user","password":"fake-secret"}')
    @patch("clearancejobs_auth.CookieJar")
    @patch("clearancejobs_auth.build_opener")
    def test_login_saves_validated_session_privately(self, opener, jar, keychain):
        jar.return_value.__iter__.return_value = iter([SimpleNamespace(
            name="laravel_token", value="fresh-token", domain="www.clearancejobs.com", path="/")])
        opener.return_value.open.return_value = io.BytesIO(b'{"csrf_token":"fresh/csrf","member":{"id":1}}')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            auth.renew_session(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            session = json.loads(path.read_text())
            self.assertEqual(session["csrf"], "fresh/csrf")
            self.assertEqual(session["cookie"], "laravel_token=fresh-token; laravel_csrf_token=fresh%2Fcsrf")
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://www.clearancejobs.com/api/v1/auth/login")
        self.assertEqual(json.loads(request.data), {"username": "test-user", "password": "fake-secret"})
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("clearancejobs_auth._keychain", return_value='{"username":"test-user","password":"fake-secret"}')
    @patch("clearancejobs_auth.build_opener")
    def test_failed_login_preserves_session_and_hides_response(self, opener, keychain):
        for outcome in (HTTPError("", 403, "fake-secret", {}, None), io.BytesIO(b'{}'), io.BytesIO(b'not json')):
            opener.return_value.open.side_effect = outcome if isinstance(outcome, HTTPError) else None
            opener.return_value.open.return_value = outcome
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "session.json"
                path.write_text("existing session")
                with self.assertRaises(RuntimeError) as failure:
                    auth.renew_session(path)
                self.assertNotIn("fake-secret", str(failure.exception))
                self.assertEqual(path.read_text(), "existing session")


if __name__ == "__main__":
    unittest.main()
