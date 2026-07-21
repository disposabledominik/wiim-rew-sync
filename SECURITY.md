# Security Policy

## Supported Versions

This project does not yet have tagged public releases with a support window. Only the latest state
of the `development` branch (and `main`, once synced from `development`) is supported — please make
sure you're on the latest commit before reporting an issue.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for a security vulnerability. Instead, use GitHub's
private vulnerability reporting: go to the repository's **Security** tab → **Report a vulnerability**.
This lets the report and any fix be reviewed privately before disclosure.

Since this tool writes configuration to devices on your local network (see the safety protocol in
[docs/architecture.md](docs/architecture.md)), please include any details relevant to device safety
(e.g. a malformed or spoofed device response triggering the issue) in your report.
