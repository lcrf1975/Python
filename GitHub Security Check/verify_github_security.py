import requests
import base64
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import NamedTuple, Optional

# --- Configuration ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REQUEST_TIMEOUT = 30
CA_BUNDLE = os.path.expanduser("~/.nscacert_combined.pem")

USERNAME: Optional[str] = None  # resolved from token in main()

_session = None
_headers = None


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        if os.path.isfile(CA_BUNDLE):
            _session.verify = CA_BUNDLE
    return _session


def get_headers():
    global _headers
    if _headers is None:
        _headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
    return _headers


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "warning": 4, "unknown": 5}
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "warning": "⚪", "unknown": "⚪"}

DOM_XSS_RULES = {"js/xss-through-dom", "js/xss", "js/xss-more-sources"}

CODEQL_WORKFLOW_TEMPLATE = """\
name: CodeQL Analysis
on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]
  schedule:
    - cron: '0 6 * * 1'
  workflow_dispatch:
jobs:
  analyze:
    name: Analyze
    runs-on: ${{{{ matrix.language == 'swift' && 'macos-latest' || matrix.language == 'csharp' && 'windows-latest' || 'ubuntu-latest' }}}}
    permissions:
      security-events: write
      actions: read
      contents: read
    strategy:
      fail-fast: false
      matrix:
        language: [ {languages} ]
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          languages: ${{{{ matrix.language }}}}
      - name: Autobuild
        uses: github/codeql-action/autobuild@v3
        if: ${{{{ matrix.language != 'javascript' && matrix.language != 'python' && matrix.language != 'ruby' && matrix.language != 'csharp' && matrix.language != 'swift' && matrix.language != 'kotlin' && matrix.language != 'cpp' }}}}
      - name: Setup MSBuild
        if: ${{{{ matrix.language == 'csharp' }}}}
        uses: microsoft/setup-msbuild@v2
      - name: Build C#
        if: ${{{{ matrix.language == 'csharp' }}}}
        run: msbuild /t:rebuild
      - name: Build Kotlin
        if: ${{{{ matrix.language == 'kotlin' }}}}
        run: |
          if [ -f gradlew ]; then
            ./gradlew build --no-daemon
          elif [ -f build.gradle ] || [ -f build.gradle.kts ]; then
            gradle build --no-daemon
          else
            echo "No Gradle wrapper found — manual build configuration required" && exit 1
          fi
      - name: Build C/C++
        if: ${{{{ matrix.language == 'cpp' }}}}
        run: |
          if [ -f CMakeLists.txt ]; then
            cmake -B build && cmake --build build
          elif [ -f Makefile ]; then
            make
          else
            echo "No CMakeLists.txt or Makefile found — manual build configuration required" && exit 1
          fi
      - name: Build Swift
        if: ${{{{ matrix.language == 'swift' }}}}
        run: |
          scheme=$(xcodebuild -list -json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('project') or d.get('workspace',{{}})).get('schemes',[''])[0])" 2>/dev/null)
          xcodebuild build -scheme "${{scheme}}" CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO
      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@v3
"""


class FixResult(NamedTuple):
    ok: Optional[bool]  # True = success, False = error, None = skipped
    message: str


def safe_json(response, default=None):
    if default is None:
        default = {}
    try:
        return response.json()
    except (ValueError, AttributeError):
        return default


class PaginationError(Exception):
    def __init__(self, status_code, message=""):
        self.status_code = status_code
        self.message = message


def api_request(method, url, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    kwargs.setdefault("headers", get_headers())
    try:
        r = get_session().request(method, url, **kwargs)
        if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(r.headers.get("X-RateLimit-Reset", 0))
            wait = max(reset - int(time.time()), 1)
            print(f"  ⏳ Rate limited — waiting {wait}s...")
            time.sleep(wait)
            try:
                retry = get_session().request(method, url, **kwargs)
                if retry.status_code == 403 and retry.headers.get("X-RateLimit-Remaining") == "0":
                    print("  ⚠️  Still rate limited after waiting — giving up")
                    return None
                return retry
            except requests.exceptions.RequestException as e:
                print(f"  ⚠️  Network error on retry: {e}")
                return None
        return r
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️  Network error: {e}")
        return None


def api_get(url, params=None):
    return api_request("GET", url, params=params)


def api_put(url, json=None):
    return api_request("PUT", url, json=json)


def api_post(url, json=None):
    return api_request("POST", url, json=json)


def api_patch(url, json=None):
    return api_request("PATCH", url, json=json)


def paginate(url, params=None):
    params = dict(params or {})
    params["per_page"] = 100
    page = 1
    while True:
        params["page"] = page
        r = api_get(url, params)
        if r is None:
            raise PaginationError(0, "Network error")
        if r.status_code != 200:
            raise PaginationError(r.status_code, safe_json(r).get("message", ""))
        data = safe_json(r, [])
        if not isinstance(data, list):
            raise PaginationError(r.status_code, "Unexpected response format")
        if not data:
            return
        yield from data
        if len(data) < 100:
            return
        page += 1


def get_repositories():
    try:
        return [item["name"] for item in paginate("https://api.github.com/user/repos", {"affiliation": "owner"})]
    except PaginationError as e:
        print(f"  ❌ Error fetching repos: HTTP {e.status_code} — {e.message}")
        return []


def get_default_branch(repo_name):
    r = api_get(f"https://api.github.com/repos/{USERNAME}/{repo_name}")
    if r and r.status_code == 200:
        return safe_json(r).get("default_branch", "main")
    return "main"


def get_repo_languages(repo_name):
    r = api_get(f"https://api.github.com/repos/{USERNAME}/{repo_name}/languages")
    if not r or r.status_code != 200:
        return []
    repo_langs = {lang.lower() for lang in safe_json(r).keys()}
    lang_map = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "javascript",
        "go": "go",
        "ruby": "ruby",
        "java": "java",
        "kotlin": "kotlin",
        "c#": "csharp",
        "c": "cpp",
        "c++": "cpp",
        "swift": "swift",
    }
    detected = []
    for gh_lang, codeql_lang in lang_map.items():
        if gh_lang in repo_langs and codeql_lang not in detected:
            detected.append(codeql_lang)
    return detected


def build_codeql_workflow(languages):
    lang_str = ", ".join(f"'{lang}'" for lang in languages)
    return CODEQL_WORKFLOW_TEMPLATE.format(languages=lang_str)


# --- Enable functions ---


def enable_dependabot(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/vulnerability-alerts"
    r = api_put(url)
    if not r:
        return False, "Network error"
    if r.status_code == 204:
        return True, "Enabled"
    msg = safe_json(r).get("message", f"HTTP {r.status_code}")
    return False, msg


def enable_secret_scanning(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}"
    r = api_patch(url, {"security_and_analysis": {"secret_scanning": {"status": "enabled"}}})
    if not r:
        return False, "Network error"
    if r.status_code == 200:
        return True, "Enabled"
    msg = safe_json(r).get("message", f"HTTP {r.status_code}")
    return False, msg


def trigger_workflow(repo_name, branch):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/actions/workflows/codeql.yml/dispatches"
    r = api_post(url, {"ref": branch})
    if not r:
        return False, "Network error"
    if r.status_code == 204:
        return True, f"Triggered on {branch}"
    return False, f"Dispatch failed: HTTP {r.status_code}"


def enable_code_scanning(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/.github/workflows/codeql.yml"
    check = api_get(url)
    if check is None:
        return False, "Network error checking existing workflow"
    already_exists = check.status_code == 200
    existing_sha = safe_json(check).get("sha") if already_exists else None

    languages = get_repo_languages(repo_name)
    if not languages:
        return False, "No CodeQL-supported languages detected"
    workflow = build_codeql_workflow(languages)
    content = base64.b64encode(workflow.encode()).decode()
    payload = {
        "message": (
            "Fix CodeQL workflow (skip autobuild for JS/Python/Ruby)"
            if already_exists
            else "Add CodeQL analysis workflow"
        ),
        "content": content,
    }
    if existing_sha:
        payload["sha"] = existing_sha
    r = api_put(url, payload)
    if not r:
        return False, "Network error"
    if r.status_code not in (200, 201):
        msg = safe_json(r).get("message", f"HTTP {r.status_code}")
        return False, msg
    lang_str = ", ".join(languages)
    prefix = f"Workflow updated ({lang_str})" if already_exists else f"Workflow created ({lang_str})"

    branch = get_default_branch(repo_name)
    ok, trigger_msg = trigger_workflow(repo_name, branch)
    if ok:
        return True, f"{prefix} & {trigger_msg}"
    return True, f"{prefix} (could not auto-trigger: {trigger_msg})"


# --- Check functions ---


def check_dependabot_alerts(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/dependabot/alerts"
    try:
        alerts = list(paginate(url, {"state": "open"}))
    except PaginationError as e:
        if e.status_code in (400, 404):
            return "skipped", "No dependency manifest"
        if e.status_code == 403:
            return "skipped", "Dependabot not enabled"
        return "error", f"HTTP {e.status_code}"
    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a.get("security_advisory", {}).get("severity", "unknown"), 5))
    return "ok", alerts


def check_secret_scanning(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/secret-scanning/alerts"
    try:
        alerts = list(paginate(url, {"state": "open"}))
    except PaginationError as e:
        if e.status_code in (404, 422, 403):
            return "skipped", "Secret scanning not enabled"
        return "error", f"HTTP {e.status_code}"
    return "ok", alerts


def check_codeql_workflow(repo_name):
    """
    Returns (status, issues) where status is 'ok', 'warning', 'absent', or 'error'.
    issues is a list of problem strings (empty when status is 'ok' or 'absent').
    """
    r = api_get(f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/.github/workflows/codeql.yml")
    if not r or r.status_code == 404:
        return "absent", []
    if r.status_code != 200:
        return "error", [f"HTTP {r.status_code}"]

    data = safe_json(r)
    encoded = data.get("content", "")
    if not encoded:
        return "warning", ["Cannot read workflow content (submodule or too large)"]
    try:
        content = base64.b64decode(encoded.replace("\n", "")).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return "warning", ["Cannot decode workflow content"]

    detected_langs = get_repo_languages(repo_name)
    issues = []

    for lang in detected_langs:
        if lang not in content:
            issues.append(f"Language '{lang}' detected in repo but missing from workflow matrix")

    if "codeql-action/init@v2" in content or "codeql-action/analyze@v2" in content:
        issues.append("Uses deprecated CodeQL action v2 — upgrade to v3")

    if "kotlin" in detected_langs and "matrix.language != 'kotlin'" not in content:
        issues.append("Kotlin missing from Autobuild exclusion — analysis may produce empty results")

    if "cpp" in detected_langs and "matrix.language != 'cpp'" not in content:
        issues.append("C/C++ missing from Autobuild exclusion — manual build step recommended")

    return ("warning", issues) if issues else ("ok", [])


def check_code_scanning(repo_name):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/code-scanning/alerts"
    try:
        alerts = list(paginate(url, {"state": "open"}))
    except PaginationError as e:
        if e.status_code in (404, 403):
            return "skipped", "Code scanning not enabled or awaiting first run"
        return "error", f"HTTP {e.status_code}"
    alerts.sort(key=lambda a: SEVERITY_ORDER.get(a.get("rule", {}).get("severity", "unknown"), 5))
    return "ok", alerts


# --- Fix functions ---


def fix_dependabot_alerts(repo_name, alerts):
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/automated-security-fixes"
    r = api_put(url)
    if not r:
        return FixResult(False, "Network error")
    if r.status_code == 204:
        return FixResult(True, f"Automated fix PRs enabled — {len(alerts)} PR(s) will be created by GitHub")
    return FixResult(False, f"HTTP {r.status_code}")


def fix_secret_alert(repo_name, alert):
    number = alert["number"]
    secret_type = alert.get("secret_type_display_name", alert.get("secret_type", "unknown"))
    ans = input(f"         Have you revoked '{secret_type}' (alert #{number})? Dismiss? [y/N] ").strip().lower()
    if ans != "y":
        return FixResult(None, "Skipped")
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/secret-scanning/alerts/{number}"
    r = api_patch(url, {"state": "resolved", "resolution": "revoked"})
    if not r:
        return FixResult(False, "Network error")
    if r.status_code == 200:
        return FixResult(True, "Dismissed as revoked")
    return FixResult(False, f"HTTP {r.status_code}")


def fix_dom_xss(repo_name, alert, path, start_line):
    branch = alert.get("most_recent_instance", {}).get("ref", "")
    url = f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/{path}"
    params = {"ref": branch} if branch else {}
    r = api_get(url, params=params)
    if not r:
        return FixResult(False, "Network error")
    if r.status_code != 200:
        return FixResult(False, f"Could not fetch file: HTTP {r.status_code}")

    data = safe_json(r)
    encoded = data.get("content", "")
    if not encoded:
        return FixResult(False, "File content unavailable (submodule, symlink, or too large)")
    raw_bytes = base64.b64decode(encoded.replace("\n", ""))
    try:
        original = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return FixResult(False, "File is not valid UTF-8 — manual fix required")
    lines = original.splitlines(keepends=True)

    if start_line < 1 or start_line > len(lines):
        return FixResult(False, "Line number out of range")

    line = lines[start_line - 1]
    stripped = line.lstrip()
    if stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("/*") or stripped.startswith("*"):
        return FixResult(None, f"Line {start_line} is a comment — manual review recommended")

    fixed_line = re.sub(r"\.innerHTML\s*=", ".textContent =", line)
    fixed_line = re.sub(r"\.html\(", ".text(", fixed_line)

    if fixed_line == line:
        return FixResult(None, f"Pattern not matched at line {start_line} — manual fix required")

    print(f"              Before  : {line.rstrip()}")
    print(f"              After   : {fixed_line.rstrip()}")
    print(f"              Why     : .innerHTML renders HTML tags, allowing script injection.")
    print(f"                        .textContent treats the value as plain text — always safe.")
    ans = input("         Apply and commit this fix? [y/N] ").strip().lower()
    if ans != "y":
        return FixResult(None, "Skipped")

    lines[start_line - 1] = fixed_line
    updated = "".join(lines)
    rule_id = alert.get("rule", {}).get("id", "xss")
    payload = {
        "message": f"Fix DOM XSS in {path} ({rule_id})",
        "content": base64.b64encode(updated.encode()).decode(),
        "sha": data["sha"],
    }
    if branch:
        payload["branch"] = branch
    patch = api_put(url, payload)
    if not patch:
        return FixResult(False, "Network error")
    if patch.status_code in (200, 201):
        return FixResult(True, f"Fixed line {start_line} and committed")
    return FixResult(False, f"Commit failed: HTTP {patch.status_code}")


def fix_code_alert(repo_name, alert):
    rule = alert.get("rule", {})
    rule_id = rule.get("id", "")
    location = alert.get("most_recent_instance", {}).get("location", {})
    path = location.get("path", "")
    start_line = location.get("start_line", 0)

    if rule_id in DOM_XSS_RULES and path:
        return fix_dom_xss(repo_name, alert, path, start_line)

    return FixResult(None, f"No auto-fix for '{rule_id}' — review manually")


# --- Describe (details + solutions, shown before asking to fix) ---


def describe_alerts(repo, alerts):
    if "dependabot" in alerts:
        print(f"\n   🔹 Dependabot — {len(alerts['dependabot'])} alert(s)")
        for a in alerts["dependabot"]:
            adv = a.get("security_advisory", {})
            vuln = a.get("security_vulnerability", {})
            sev = adv.get("severity", "unknown")
            icon = SEVERITY_ICON.get(sev, "⚪")
            dep_pkg = a.get("dependency", {}).get("package", {})
            pkg = dep_pkg.get("name", "unknown")
            ecosystem = dep_pkg.get("ecosystem", "")
            cve = adv.get("cve_id") or adv.get("ghsa_id", "N/A")
            affected = vuln.get("vulnerable_version_range", "unknown range")
            patched = (vuln.get("first_patched_version") or {}).get("identifier", "no patch available")
            manifest = a.get("dependency", {}).get("manifest_path", "")
            print(f"        {icon} [{sev.upper()}] {pkg} ({ecosystem})")
            print(f"             CVE/ID   : {cve}")
            print(f"             Issue    : {adv.get('summary', 'No summary')}")
            print(f"             Affected : {affected}")
            print(f"             Fix      : upgrade to {patched}")
            if manifest:
                print(f"             File     : {manifest}")
        print(f"\n        💡 Solution: GitHub will auto-open a PR to upgrade each package.")

    if "secrets" in alerts:
        print(f"\n   🔹 Secrets — {len(alerts['secrets'])} alert(s)")
        for a in alerts["secrets"]:
            number = a["number"]
            secret_type = a.get("secret_type_display_name", a.get("secret_type", "unknown"))
            html_url = a.get("html_url", "")
            loc_url = f"https://api.github.com/repos/{USERNAME}/{repo}/secret-scanning/alerts/{number}/locations"
            loc_r = api_get(loc_url)
            locations = safe_json(loc_r, []) if loc_r and loc_r.status_code == 200 else []
            print(f"        🔴 {secret_type}")
            if html_url:
                print(f"             Alert URL: {html_url}")
            for loc in locations:
                details = loc.get("details", {})
                path = details.get("path", "")
                line = details.get("start_line", "")
                sha = details.get("blob_sha", "")[:7]
                if path:
                    print(f"             Found at : {path}:{line} (commit {sha})")
        print(f"\n        💡 Solution: Revoke the credential at its provider, then dismiss the alert.")
        print(f"           Also consider removing it from git history with git-filter-repo.")

    if "code" in alerts:
        print(f"\n   🔹 Code scanning — {len(alerts['code'])} alert(s)")
        for a in alerts["code"]:
            rule = a.get("rule", {})
            rule_id = rule.get("id", "")
            rule_desc = rule.get("description", "")
            rule_full = rule.get("full_description", "")
            instance = a.get("most_recent_instance", {})
            location = instance.get("location", {})
            message = instance.get("message", {}).get("text", "")
            path = location.get("path", "")
            line = location.get("start_line", "")
            sev = rule.get("severity", "unknown")
            html_url = a.get("html_url", "")
            print(f"        {SEVERITY_ICON.get(sev, '⚪')} [{sev.upper()}] {rule_desc}")
            if rule_full and rule_full != rule_desc:
                print(f"             Detail   : {rule_full}")
            if message:
                print(f"             Instance : {message}")
            print(f"             File     : {path}:{line}")
            if html_url:
                print(f"             URL      : {html_url}")
            if rule_id in DOM_XSS_RULES:
                print(f"             💡 Solution: Replace .innerHTML with .textContent (auto-fix available)")
            else:
                print(f"             💡 Solution: Manual fix required — review the URL above")


# --- Fix flow ---


def _fix_icon(result: FixResult) -> str:
    if result.ok is True:
        return "✅"
    if result.ok is False:
        return "❌"
    return "⚪"


def run_fixes(repos_with_alerts):
    for repo, alerts in repos_with_alerts.items():
        total = sum(len(v) for v in alerts.values())
        ans = input(f"\n   Fix {total} issue(s) in '{repo}'? [y/N] ").strip().lower()
        if ans != "y":
            continue

        if "dependabot" in alerts:
            print("\n      Applying Dependabot fix...")
            result = fix_dependabot_alerts(repo, alerts["dependabot"])
            print(f"      {_fix_icon(result)} {result.message}")

        if "secrets" in alerts:
            print("\n      Fixing secrets...")
            for alert in alerts["secrets"]:
                result = fix_secret_alert(repo, alert)
                print(f"      {_fix_icon(result)} {result.message}")

        if "code" in alerts:
            print("\n      Fixing code scanning alerts...")
            for alert in alerts["code"]:
                result = fix_code_alert(repo, alert)
                print(f"      {_fix_icon(result)} {result.message}")

    print()


# --- Display ---


def print_repo_report(repo_name, dep_result, secret_result, code_result, workflow_result):
    dep_status, dep_data = dep_result
    secret_status, secret_data = secret_result
    code_status, code_data = code_result
    workflow_status, workflow_issues = workflow_result

    dep_alerts = dep_data if dep_status == "ok" else []
    secret_alerts = secret_data if secret_status == "ok" else []
    code_alerts = code_data if code_status == "ok" else []

    total_alerts = len(dep_alerts) + len(secret_alerts) + len(code_alerts)
    repo_icon = "🔴" if total_alerts > 0 else "✅"

    print(f"\n{repo_icon}  {repo_name}")
    print(f"   {'─' * 44}")

    if dep_status == "skipped":
        print(f"   🔹 Dependabot     ⚪ {dep_data}")
    elif dep_status == "error":
        print(f"   🔹 Dependabot     ❌ Error ({dep_data})")
    elif dep_alerts:
        print(f"   🔹 Dependabot     ⚠️  {len(dep_alerts)} open alert(s)")
        for a in dep_alerts:
            adv = a.get("security_advisory", {})
            sev = adv.get("severity", "unknown")
            icon = SEVERITY_ICON.get(sev, "⚪")
            pkg = a.get("dependency", {}).get("package", {}).get("name", "unknown")
            summary = adv.get("summary", "No summary")
            print(f"        {icon} [{sev.upper()}] {pkg}: {summary}")
    else:
        print(f"   🔹 Dependabot     ✅ No open alerts")

    if secret_status == "skipped":
        print(f"   🔹 Secrets        ⚪ {secret_data}")
    elif secret_status == "error":
        print(f"   🔹 Secrets        ❌ Error ({secret_data})")
    elif secret_alerts:
        print(f"   🔹 Secrets        ⚠️  {len(secret_alerts)} open alert(s)")
        for a in secret_alerts:
            stype = a.get("secret_type_display_name", a.get("secret_type", "unknown"))
            print(f"        🔴 [SECRET] {stype}")
    else:
        print(f"   🔹 Secrets        ✅ No open alerts")

    if code_status == "skipped":
        if workflow_status == "absent":
            print(f"   🔹 Code scanning  ⚪ Not enabled")
        elif workflow_status == "ok":
            print(f"   🔹 Code scanning  ⏳ Workflow present — awaiting first Actions run")
        elif workflow_status == "warning":
            print(f"   🔹 Code scanning  ⚠️  Workflow has issues:")
            for issue in workflow_issues:
                print(f"        ⚠️  {issue}")
        else:
            print(f"   🔹 Code scanning  ⚪ {code_data}")
    elif code_status == "error":
        print(f"   🔹 Code scanning  ❌ Error ({code_data})")
    elif code_alerts:
        print(f"   🔹 Code scanning  ⚠️  {len(code_alerts)} open alert(s)")
        for a in code_alerts:
            rule = a.get("rule", {})
            sev = rule.get("severity", "unknown")
            icon = SEVERITY_ICON.get(sev, "⚪")
            desc = rule.get("description", "No description")
            print(f"        {icon} [{sev.upper()}] {desc}")
        if workflow_status == "warning":
            for issue in workflow_issues:
                print(f"        ⚠️  Workflow: {issue}")
    else:
        print(f"   🔹 Code scanning  ✅ No open alerts")
        if workflow_status == "warning":
            for issue in workflow_issues:
                print(f"        ⚠️  Workflow: {issue}")

    return total_alerts, dep_alerts, secret_alerts, code_alerts


# --- Main flows ---


def scan_repo(repo):
    dep = check_dependabot_alerts(repo)
    secret = check_secret_scanning(repo)
    code = check_code_scanning(repo)
    workflow = check_codeql_workflow(repo)
    return repo, dep, secret, code, workflow


def run_enable(repos):
    print(f"\n⚙️   Enabling security features for {len(repos)} repo(s)...\n")
    for i, repo in enumerate(repos, 1):
        print(f"   [{i}/{len(repos)}] 📦 {repo}")
        ok, msg = enable_dependabot(repo)
        print(f"      {'✅' if ok else '⚠️ '} Dependabot:      {msg}")
        ok, msg = enable_secret_scanning(repo)
        print(f"      {'✅' if ok else '⚠️ '} Secret scanning: {msg}")
        ok, msg = enable_code_scanning(repo)
        print(f"      {'✅' if ok else '⚠️ '} Code scanning:   {msg}")
    print(f"\n{'=' * 50}")
    print("✅  Done. Run again to scan for alerts.")
    print()


def run_scan(repos):
    total_vulns = 0
    repos_with_alerts = {}
    results = {}

    print(f"   Scanning {len(repos)} repo(s)...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_repo = {executor.submit(scan_repo, repo): repo for repo in repos}
        completed = 0
        for future in as_completed(future_to_repo):
            completed += 1
            repo = future_to_repo[future]
            progress = f"\r   Progress: [{completed}/{len(repos)}] {repo}"
            print(progress, end="", flush=True)
            results[repo] = future.result()
    print("\r" + " " * 60 + "\r", end="")

    for repo in repos:
        _, dep_result, secret_result, code_result, workflow_result = results[repo]
        count, dep_alerts, secret_alerts, code_alerts = print_repo_report(
            repo, dep_result, secret_result, code_result, workflow_result
        )
        total_vulns += count
        if count > 0:
            alerts = {}
            if dep_alerts:
                alerts["dependabot"] = dep_alerts
            if secret_alerts:
                alerts["secrets"] = secret_alerts
            if code_alerts:
                alerts["code"] = code_alerts
            repos_with_alerts[repo] = alerts

    print(f"\n{'=' * 50}")
    if total_vulns == 0:
        print("✅  All clear — no open security alerts found.")
        print()
        return 0

    print(f"⚠️   Scan complete — {total_vulns} open alert(s) across {len(repos_with_alerts)} repo(s):")
    for repo, alerts in repos_with_alerts.items():
        count = sum(len(v) for v in alerts.values())
        print(f"     • {repo}: {count} alert(s)")

    print(f"\n{'=' * 50}")
    print("📋  Issue Details & Proposed Solutions")
    print(f"{'=' * 50}")
    for repo, alerts in repos_with_alerts.items():
        print(f"\n📦  {repo}")
        print(f"   {'─' * 44}")
        describe_alerts(repo, alerts)

    ans = input("\n🔧  Would you like to fix these issues now? [y/N] ").strip().lower()
    if ans == "y":
        run_fixes(repos_with_alerts)

    return total_vulns


def main():
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set. Export it before running:")
        print("   export GITHUB_TOKEN='ghp_...'")
        sys.exit(1)

    r = api_get("https://api.github.com/user")
    if not r or r.status_code != 200:
        print("❌ Could not authenticate with GitHub API.")
        sys.exit(1)
    global USERNAME
    USERNAME = safe_json(r).get("login")
    if not USERNAME:
        print("❌ Could not determine GitHub username from token.")
        sys.exit(1)

    print(f"\n🔍  GitHub Security Scan — {USERNAME}")
    print("=" * 50)
    print("Fetching repositories...")

    repos = get_repositories()
    if not repos:
        print("No repositories found or authentication failed.")
        sys.exit(1)

    print(f"Found {len(repos)} repositories.")

    ans = input("\n⚙️  Enable all security features before scanning? [y/N] ").strip().lower()
    if ans == "y":
        run_enable(repos)

    print()
    vulns = run_scan(repos)
    sys.exit(1 if vulns > 0 else 0)


if __name__ == "__main__":
    main()
