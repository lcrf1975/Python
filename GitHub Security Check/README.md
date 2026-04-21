# GitHub Security Scanner

A CLI tool that audits all your GitHub repositories for security issues, validates CodeQL workflow configuration, and applies automated fixes where possible.

## Features

- **Dependabot alerts** — lists open vulnerability alerts sorted by severity, enables automated fix PRs
- **Secret scanning** — detects exposed credentials with file/line location, guides dismissal after revocation
- **Code scanning (CodeQL)** — reports open alerts, validates your workflow YAML for correctness, enables scanning on repos that lack it
- **Workflow validation** — checks that existing `codeql.yml` covers all detected languages, uses current action versions, and has correct build steps for Kotlin and C/C++
- **Auto-fix** — DOM XSS (`innerHTML` → `textContent`) is patched and committed directly via the API
- **Parallel scanning** — all repos are scanned concurrently (5 workers) for fast results

## Requirements

- Python 3.8+
- `requests` library

```bash
pip install requests
```

## Setup

Export a GitHub Personal Access Token with the following scopes:

| Scope | Required for |
|---|---|
| `repo` | Read repo contents, write workflow files |
| `security_events` | Read/write Dependabot, secret scanning, and code scanning alerts |
| `workflow` | Create/update GitHub Actions workflow files |

```bash
export GITHUB_TOKEN='ghp_...'
```

## Usage

```bash
python verify_github_security.py
```

The script will:

1. Authenticate and resolve your GitHub username from the token
2. Fetch all repositories you own
3. Prompt whether to **enable** security features (Dependabot, secret scanning, CodeQL) across all repos before scanning
4. **Scan** all repos in parallel and print a report
5. Show detailed issue descriptions and proposed solutions for any findings
6. Prompt whether to **apply fixes** interactively

## Report output

```
✅  my-clean-repo
   ────────────────────────────────────────────
   🔹 Dependabot     ✅ No open alerts
   🔹 Secrets        ✅ No open alerts
   🔹 Code scanning  ✅ No open alerts

🔴  my-vulnerable-repo
   ────────────────────────────────────────────
   🔹 Dependabot     ⚠️  2 open alert(s)
        🟠 [HIGH] lodash: Prototype Pollution
        🟡 [MEDIUM] axios: SSRF vulnerability
   🔹 Secrets        ⚠️  1 open alert(s)
        🔴 [SECRET] GitHub Personal Access Token
   🔹 Code scanning  ⚠️  1 open alert(s)
        🟠 [HIGH] DOM text reinterpreted as HTML
```

## Workflow validation

When a `codeql.yml` already exists, the script checks for:

- Languages detected in the repo that are absent from the workflow matrix
- Use of deprecated CodeQL action v2 (flags upgrade to v3)
- Kotlin missing from the Autobuild exclusion list (causes empty analysis)
- C/C++ missing from the Autobuild exclusion list (build step required)

## Auto-fixes

| Issue | Fix applied |
|---|---|
| Dependabot alerts | Enables GitHub automated security fix PRs |
| Secret scanning alert | Guides revocation, then dismisses via API |
| DOM XSS (`js/xss`, `js/xss-through-dom`, `js/xss-more-sources`) | Replaces `.innerHTML =` with `.textContent =` and `.html(` with `.text(`, commits to repo |
| CodeQL workflow absent | Creates `.github/workflows/codeql.yml` tailored to detected languages |
| CodeQL workflow outdated | Overwrites with corrected template |

All fixes require interactive confirmation before being applied.

## Corporate / proxy environments

If `~/.nscacert_combined.pem` exists, it is used as the CA bundle for all HTTPS requests (Netskope and similar SSL-inspecting proxies).

## Exit codes

| Code | Meaning |
|---|---|
| `0` | No open security alerts found |
| `1` | One or more open alerts remain, or authentication failed |
