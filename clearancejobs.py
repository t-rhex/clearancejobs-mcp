"""Read-only access to ClearanceJobs search, saved jobs, applications, and descriptions."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


BASE_URL = "https://www.clearancejobs.com"
SEARCH_URL = BASE_URL + "/api/v1/jobs/search"
SESSION_FILE = Path.home() / ".config/clearancejobs/session.json"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "API-Version": "2026-02-17",
    "X-Device-Type": "web",
    "X-Requested-With": "XMLHttpRequest",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Session credentials must never follow a redirect to another destination.
        return None


def _load_session(session_file):
    path = Path(session_file)
    if path.stat().st_mode & 0o077:
        raise ValueError("Session file must have owner-only permissions (chmod 600)")
    session = json.loads(path.read_text())
    for key in ("cookie", "csrf"):
        value = session[key]
        if not isinstance(value, str) or not value or "\r" in value or "\n" in value:
            raise ValueError("Invalid session file")
    return session


def _renew_session(session_file, expired_session):
    from clearancejobs_auth import renew_session
    renew_session(session_file, expired_session=expired_session)


def _request(url, *, payload=None, session_file=None, _renew=True):
    headers = HEADERS.copy()
    if session_file is not None:
        if urlsplit(url).netloc != "www.clearancejobs.com" or urlsplit(url).scheme != "https":
            raise ValueError("Authenticated requests require https://www.clearancejobs.com")
        try:
            session = _load_session(session_file)
            headers.update({"Cookie": session["cookie"], "X-CSRF-TOKEN": session["csrf"]})
        except FileNotFoundError:
            if _renew:
                _renew_session(session_file, None)
                return _request(url, payload=payload, session_file=session_file, _renew=False)
            raise RuntimeError("Session file missing after login") from None
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Cannot load session from {session_file}: {exc}") from exc
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    try:
        open_url = urlopen if session_file is None else build_opener(_NoRedirect()).open
        with open_url(request, timeout=30) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        if session_file is not None and _renew and exc.code in (401, 419):
            _renew_session(session_file, session)
            return _request(url, payload=payload, session_file=session_file, _renew=False)
        hint = "; sign in again and refresh the session file" if session_file is not None and exc.code in (301, 302, 303, 307, 308, 401, 403, 419) else ""
        raise RuntimeError(f"ClearanceJobs returned HTTP {exc.code}{hint}; no automatic retry") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Could not connect to ClearanceJobs") from exc
    except UnicodeError as exc:
        raise RuntimeError("ClearanceJobs returned an invalid text response") from exc


def _listing(url, **kwargs):
    try:
        result = json.loads(_request(url, **kwargs))
    except ValueError as exc:
        raise RuntimeError("ClearanceJobs returned an invalid JSON response") from exc
    if (not isinstance(result, dict) or not isinstance(result.get("data"), list)
            or not isinstance(result.get("meta"), dict)
            or not isinstance(result["meta"].get("pagination"), dict)):
        raise RuntimeError("ClearanceJobs listing response schema changed")
    return result


def _validate_page(page, limit=20):
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit must be an integer between 1 and 20")


def search(keywords="", *, remote=False, state=None, page=1, limit=20):
    """Return one search page, including original pagination metadata."""
    _validate_page(page, limit)
    if not isinstance(keywords, str) or type(remote) is not bool:
        raise ValueError("keywords must be text and remote must be a boolean")
    if state not in (None, "FL"):
        raise ValueError("state must be FL (Florida) or None")
    payload = {"keywords": keywords, "sort_info": "timestamp desc", "page": page, "limit": limit}
    if remote:
        payload["remote"] = True
    if state == "FL":
        payload["loc"] = [9]  # Florida's state ID, observed in the site's State filter.
    # shortcut: one page per call; add scheduling only when refresh needs are defined.
    return _listing(SEARCH_URL, payload=payload)


def saved_jobs(*, page=1, limit=20, session_file=SESSION_FILE):
    _validate_page(page, limit)
    return _listing(f"{BASE_URL}/api/v1/jobs/saved?per_page={limit}&page={page}", session_file=session_file)


def applications(*, page=1, session_file=SESSION_FILE):
    _validate_page(page)
    return _listing(f"{BASE_URL}/api/v1/jobs/applications?page={page}", session_file=session_file)


class _JobPostingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.collecting = False
        self.parts = []
        self.postings = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.collecting = True
            self.parts = []

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.collecting:
            self.collecting = False
            try:
                value = json.loads("".join(self.parts))
            except ValueError:
                return
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    self.postings.append(item)


def job_details(url):
    """Return public JobPosting JSON-LD, including the full description's HTML."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in ("www.clearancejobs.com", "clearancejobs.com")
            or not re.fullmatch(r"/jobs/[0-9]+(?:/[^/]+)?", parsed.path)):
        raise ValueError("Use a ClearanceJobs job URL: https://www.clearancejobs.com/jobs/ID[/slug]")
    parser = _JobPostingParser()
    parser.feed(_request(BASE_URL + parsed.path))
    if not parser.postings or not isinstance(parser.postings[0].get("description"), str) or not parser.postings[0]["description"]:
        raise RuntimeError("No full JobPosting description found; the job may be closed or the page changed")
    return parser.postings[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keywords", nargs="?", default="")
    parser.add_argument("--remote", action="store_true", help="Use the site's Remote/Hybrid filter")
    parser.add_argument("--state", choices=["FL"], help="Restrict search to Florida")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=20)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--saved", action="store_true")
    modes.add_argument("--applications", action="store_true")
    modes.add_argument("--job-url", help="Read a full description from a public job page")
    args = parser.parse_args()
    if (args.saved or args.applications or args.job_url) and (args.keywords or args.remote or args.state):
        parser.error("keywords, --remote, and --state apply only to search")
    if (args.applications or args.job_url) and args.limit != 20:
        parser.error("--limit applies only to search and saved jobs")
    if args.job_url and args.page != 1:
        parser.error("--page does not apply to job details")
    try:
        if args.saved:
            result = saved_jobs(page=args.page, limit=args.limit)
        elif args.applications:
            result = applications(page=args.page)
        elif args.job_url:
            result = job_details(args.job_url)
        else:
            result = search(args.keywords, remote=args.remote, state=args.state, page=args.page, limit=args.limit)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
