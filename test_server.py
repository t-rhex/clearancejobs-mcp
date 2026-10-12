import unittest
from unittest.mock import patch

from mcp import Client

from clearancejobs_mcp import mcp


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_and_input_validation(self):
        async with Client(mcp) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {
                "search_jobs", "get_saved_jobs", "get_applications", "get_job_details",
            })
            self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))
            with patch("clearancejobs_mcp.clearancejobs.search") as search:
                for args in ({"keywords": "devops", "limit": 21},
                             {"keywords": "devops", "page": 0}):
                    result = await client.call_tool("search_jobs", args)
                    self.assertTrue(result.is_error)
                search.assert_not_called()

    async def test_florida_filter_is_exposed_and_forwarded(self):
        raw = {"data": [], "meta": {"pagination": {"total": 0}}}
        async with Client(mcp) as client:
            with patch("clearancejobs_mcp.clearancejobs.search", return_value=raw) as search:
                result = await client.call_tool("search_jobs", {"keywords": "devops", "state": "FL"})
                self.assertFalse(result.is_error)
                self.assertEqual(search.call_args.kwargs["state"], "FL")
                invalid = await client.call_tool("search_jobs", {"keywords": "devops", "state": "CA"})
                self.assertTrue(invalid.is_error)
                self.assertEqual(search.call_count, 1)

    async def test_compact_lists_use_job_ids_and_keep_status(self):
        raw = {"data": [{"id": 999, "job_id": 123, "job_name": "Example",
                         "status": "external_apply", "applied_status": None,
                         "company_logo_url": "unnecessary", "preview_text": "x" * 1000}],
               "meta": {"pagination": {"current_page": 1, "total_pages": 2}}}
        async with Client(mcp) as client:
            for tool, backend in (("get_applications", "applications"),
                                  ("get_saved_jobs", "saved_jobs"),
                                  ("search_jobs", "search")):
                with patch("clearancejobs_mcp.clearancejobs." + backend, return_value=raw):
                    result = await client.call_tool(tool, {"keywords": "devops"} if tool == "search_jobs" else {})
                    self.assertFalse(result.is_error)
                    data = result.structured_content
                    job = data["jobs"][0]
                    self.assertEqual(job["job_id"], 123)
                    self.assertEqual(job["url"], "https://www.clearancejobs.com/jobs/123")
                    self.assertEqual(job["status"], "external_apply")
                    self.assertIn("applied_status", job)
                    self.assertNotIn("company_logo_url", job)
                    self.assertLess(len(job["preview"]), 300)
                    self.assertEqual(data["pagination"]["total_pages"], 2)

    async def test_full_description_preserves_text_and_paragraphs(self):
        raw = {"@context": "schema", "@type": "JobPosting", "title": "Example",
               "description": "<p>First &amp; full.</p><ul><li>Second</li><li>Third</li></ul>"}
        async with Client(mcp) as client:
            with patch("clearancejobs_mcp.clearancejobs.job_details", return_value=raw) as details:
                result = await client.call_tool("get_job_details", {"job_id": 123})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["description"], "First & full.\nSecond\nThird")
                details.assert_called_once_with(url="https://www.clearancejobs.com/jobs/123")
                self.assertNotIn("@context", result.structured_content)
                invalid = await client.call_tool("get_job_details", {"job_id": -1})
                self.assertTrue(invalid.is_error)
                self.assertEqual(details.call_count, 1)

    async def test_session_error_is_reported(self):
        async with Client(mcp) as client:
            with patch("clearancejobs_mcp.clearancejobs.saved_jobs", side_effect=RuntimeError("ClearanceJobs returned HTTP 401; refresh session")):
                result = await client.call_tool("get_saved_jobs", {})
                self.assertTrue(result.is_error)
                self.assertIn("refresh session", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
