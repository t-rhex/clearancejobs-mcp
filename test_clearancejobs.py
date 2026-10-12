import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from clearancejobs import _NoRedirect, applications, job_details, saved_jobs, search


class SearchTests(unittest.TestCase):
    @patch("clearancejobs.urlopen")
    def test_payload_and_pagination(self, open_url):
        response = {"data": [{"id": 123}], "meta": {"pagination": {"next_page": 3}}}
        open_url.return_value = io.BytesIO(json.dumps(response).encode())
        self.assertEqual(search("devsecops", remote=True, page=2, limit=2), response)
        request = open_url.call_args.args[0]
        self.assertEqual(json.loads(request.data), {
            "keywords": "devsecops", "sort_info": "timestamp desc",
            "remote": True, "page": 2, "limit": 2,
        })
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 30)

    @patch("clearancejobs.urlopen")
    def test_invalid_input_does_not_send_requests(self, open_url):
        for kwargs in ({"page": 0}, {"page": True}, {"limit": 21}, {"limit": 0},
                       {"remote": "yes"}, {"keywords": None}, {"state": "CA"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search(**kwargs)
        open_url.assert_not_called()

    @patch("clearancejobs.urlopen")
    def test_florida_filter_composes_with_search(self, open_url):
        open_url.return_value = io.BytesIO(b'{"data":[],"meta":{"pagination":{}}}')
        search("platform engineering", state="FL", remote=True, page=2, limit=5)
        self.assertEqual(json.loads(open_url.call_args.args[0].data), {
            "keywords": "platform engineering", "sort_info": "timestamp desc",
            "page": 2, "limit": 5, "remote": True, "loc": [9],
        })

    @patch("clearancejobs.urlopen")
    def test_bad_json_and_schema(self, open_url):
        for body in (b"<html>blocked</html>", b"[]", b'{"data":[],"meta":{}}'):
            open_url.return_value = io.BytesIO(body)
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                search()

    @patch("clearancejobs.urlopen")
    def test_rate_limit_stops_without_retry(self, open_url):
        open_url.side_effect = HTTPError("https://www.clearancejobs.com", 429, "Too many", {}, None)
        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            search()
        self.assertEqual(open_url.call_count, 1)

    @patch("clearancejobs.build_opener")
    def test_authenticated_lists(self, opener):
        response = {"data": [{"job_id": 123}], "meta": {"pagination": {"total": 1}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text(json.dumps({"cookie": "laravel_token=test", "csrf": "test-csrf"}))
            path.chmod(0o600)
            for getter, suffix in ((saved_jobs, "/jobs/saved?per_page=20&page=2"),
                                   (applications, "/jobs/applications?page=2")):
                opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
                self.assertEqual(getter(page=2, session_file=path), response)
                request = opener.return_value.open.call_args.args[0]
                self.assertTrue(request.full_url.endswith(suffix))
                self.assertEqual(request.get_method(), "GET")
                self.assertEqual(request.get_header("Cookie"), "laravel_token=test")
                self.assertEqual(request.get_header("X-csrf-token"), "test-csrf")
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "owner-only"):
                saved_jobs(session_file=path)
            path.chmod(0o600)
            path.write_text(json.dumps({"cookie": "test\r\nInjected: bad", "csrf": "test"}))
            with self.assertRaisesRegex(RuntimeError, "Invalid session"):
                saved_jobs(session_file=path)
        self.assertEqual(opener.return_value.open.call_count, 2)

    def test_credentials_do_not_follow_redirects(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    @patch("clearancejobs.urlopen")
    def test_full_description_from_structured_data(self, open_url):
        html = b'''<script type="application/ld+json">{"@type":"Organization"}</script>
        <script type="application/ld+json">{"@type":"JobPosting","description":"<p>Full &amp; complete</p>"}</script>'''
        open_url.return_value = io.BytesIO(html)
        result = job_details("https://www.clearancejobs.com/jobs/123/example?source=job_search")
        self.assertEqual(result["description"], "<p>Full &amp; complete</p>")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://www.clearancejobs.com/jobs/123/example")
        self.assertIsNone(request.get_header("Cookie"))
        for url in ("https://evil.example/jobs/123/example", "http://www.clearancejobs.com/jobs/123/example",
                    "https://www.clearancejobs.com@evil.example/jobs/123/example"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                job_details(url)
        self.assertEqual(open_url.call_count, 1)
        open_url.return_value = io.BytesIO(b"<html>Job closed</html>")
        with self.assertRaisesRegex(RuntimeError, "No full JobPosting"):
            job_details("https://www.clearancejobs.com/jobs/123/example")


if __name__ == "__main__":
    unittest.main()
