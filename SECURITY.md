# Security

Please use GitHub's private vulnerability reporting feature for this repository
to report security issues. Do not include passwords, cookies, CSRF tokens,
Keychain exports, resumes, application histories, or classified information in
issues, pull requests, screenshots, or logs.

Only the latest beta is maintained. This project has no formal security audit.
Credentials remain local, but an MCP client receives account data you request.
Review your AI client's data settings and only connect clients you trust.

Keychain permission applies to the Python interpreter. Other software running
under an allowed interpreter may have access, subject to macOS controls. The
session file is a credential with owner-only permissions, not encrypted storage.
Use a trusted macOS account and interpreter. File locks coordinate renewal only
for processes using the same session path; a separate device or an explicit
forced login may still change the website's session state.

If credentials are exposed, change your password and revoke active sessions
through ClearanceJobs where available, remove the local Keychain item with
`clearancejobs-auth forget`, and remove the local session file. Deleting local
files alone does not revoke remote sessions.
