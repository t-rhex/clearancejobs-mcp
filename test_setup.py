import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import clearancejobs_setup as setup


class SetupTests(unittest.TestCase):
    def test_generic_config_uses_installed_python_without_secrets(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["clearancejobs-setup"]), contextlib.redirect_stdout(output):
            self.assertEqual(setup.main(), 0)
        config = json.loads(output.getvalue())["mcpServers"]["clearancejobs"]
        self.assertEqual(config, {"command": sys.executable, "args": ["-m", "clearancejobs_mcp"]})

    @patch("clearancejobs_setup.subprocess.run")
    @patch("clearancejobs_setup.shutil.which", return_value="/test/bin/codex")
    def test_codex_registration_uses_argv_and_preserves_exit_status(self, which, run):
        run.return_value.returncode = 7
        with patch.object(sys, "argv", ["clearancejobs-setup", "--codex"]):
            self.assertEqual(setup.main(), 7)
        run.assert_called_once_with(["/test/bin/codex", "mcp", "add", "clearancejobs", "--",
                                     sys.executable, "-m", "clearancejobs_mcp"], check=False)

    @patch("clearancejobs_setup.shutil.which", return_value=None)
    def test_missing_codex_has_actionable_error(self, which):
        output = io.StringIO()
        with patch.object(sys, "argv", ["clearancejobs-setup", "--codex"]), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as failure:
                setup.main()
        self.assertEqual(failure.exception.code, 1)
        self.assertIn("Codex CLI not found", output.getvalue())


if __name__ == "__main__":
    unittest.main()
