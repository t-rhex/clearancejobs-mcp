# Contributing

Keep this project read-only, local, and small. Do not add auto-apply, recruiter
messaging, CAPTCHA bypass, credential collection, or bulk crawling. Discuss
larger features in an issue before implementation.

Use Python 3.13+ and uv:

```sh
uv sync --locked
uv run python -m unittest -v
uv build
uv run python check_beta.py
```

CI performs these offline application checks on macOS. Dependency installation
needs network access; the tests and MCP catalog check do not access ClearanceJobs
or Keychain. The two live checks documented in README are opt-in and must never
run in CI. Do not put account credentials in GitHub secrets for this project.

Use fake data for fixtures and demonstrations. Update MANIFEST.in and the release
allowlist in check_beta.py deliberately when adding distributable files. Inspect
both source and wheel archives before a release; .gitignore is not a release
manifest. Never archive the working directory or a virtual environment.

Open an issue with your macOS/Python/package versions, the command you ran,
expected behavior, and a redacted error. Avoid full account responses. Security
reports belong in private vulnerability reporting, as described in SECURITY.md.
