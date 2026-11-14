"""Probe Superset role, dataset and CSRF boundaries on an isolated local stack.

Usage: uv run scripts/integration_superset_security.py --isolated-url http://localhost:8089

Set SUPERSET_SECURITY_USERS_JSON to a JSON object with admin, viewer, query and no_role entries, each containing
username and password. Set SUPERSET_SECURITY_ALLOWED_DATASET_ID and SUPERSET_SECURITY_DENIED_DATASET_ID to exercise
Superset dataset authorization with the query user. Write probes exercise invalid-CSRF rejection for every role and
valid-CSRF role rejection for non-admins; the script never submits a valid-CSRF mutation as an authorized role. Run it
only against an isolated test stack with four dedicated test accounts.
"""

import argparse
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

SEMANTIC_API = "/extensions/text-to-bi/superset-semantic-layer/semantic-layer"
AGENT_QUERY_API = "/extensions/text-to-bi/superset-ai-agent/semantic-query"
ROLE_NAMES = ("admin", "viewer", "query", "no_role")


def request(opener, base_url, path, method="GET", body=None, headers=None):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
    http_request = urllib.request.Request(f"{base_url}{path}", data=payload, headers=request_headers, method=method)
    try:
        with opener.open(http_request, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", errors="replace")


def login(base_url, account):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    status, page = request(opener, base_url, "/login/")
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page if isinstance(page, str) else "")
    if status != 200 or not token:
        raise RuntimeError(f"login form unavailable ({status})")
    form = urllib.parse.urlencode({"csrf_token": token.group(1), **account}).encode()
    http_request = urllib.request.Request(f"{base_url}/login/", data=form)
    with opener.open(http_request, timeout=30):
        pass
    status, me = request(opener, base_url, "/api/v1/me/")
    if status != 200 or not isinstance(me, dict) or me.get("result", {}).get("username") != account["username"]:
        raise RuntimeError(f"login failed for {account['username']}")
    return opener, token.group(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--isolated-url", required=True, help="Local, disposable Superset stack URL")
    arguments = parser.parse_args(argv)
    parsed_url = urllib.parse.urlparse(arguments.isolated_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"localhost", "127.0.0.1"} or parsed_url.username or parsed_url.password:
        parser.error("--isolated-url must be an HTTP localhost URL without embedded credentials")
    base_url = arguments.isolated_url.rstrip("/")
    accounts = json.loads(os.environ.get("SUPERSET_SECURITY_USERS_JSON", "{}"))
    if set(accounts) != set(ROLE_NAMES) or any(set(accounts[role]) != {"username", "password"} for role in ROLE_NAMES):
        parser.error("SUPERSET_SECURITY_USERS_JSON must provide username and password for admin, viewer, query and no_role")

    sessions = {role: login(base_url, accounts[role]) for role in ROLE_NAMES}
    openers = {role: session[0] for role, session in sessions.items()}
    failures = []

    def check(role, method, path, expected, body=None, headers=None):
        status, payload = request(openers[role], base_url, path, method, body, headers)
        passed = status in expected
        print(f"{'ok  ' if passed else 'FAIL'} {role:7} {status} {method:6} {path}")
        if not passed:
            failures.append(f"{role} {method} {path}: expected {sorted(expected)}, got {status}, body {str(payload)[:200]}")
        return payload

    for role in ROLE_NAMES:
        payload = check(role, "GET", f"{SEMANTIC_API}/access", {200})
        expected_flags = {"admin": (True, True), "viewer": (True, False), "query": (False, True), "no_role": (False, False)}
        if isinstance(payload, dict) and (payload.get("can_view"), payload.get("can_query")) != expected_flags[role]:
            failures.append(f"{role} /access returned wrong view/query flags")
        check(role, "GET", f"{SEMANTIC_API}/datasets/query-metadata", {200} if role in {"admin", "query"} else {403})
        check(role, "GET", f"{AGENT_QUERY_API}/semantic-catalog", {200} if role in {"admin", "query"} else {403})
        check(role, "GET", f"{SEMANTIC_API}/glossary", {200} if role in {"admin", "viewer"} else {403})

    allowed = os.environ.get("SUPERSET_SECURITY_ALLOWED_DATASET_ID")
    denied = os.environ.get("SUPERSET_SECURITY_DENIED_DATASET_ID")
    if bool(allowed) != bool(denied):
        parser.error("set both SUPERSET_SECURITY_ALLOWED_DATASET_ID and SUPERSET_SECURITY_DENIED_DATASET_ID")
    if allowed:
        if not allowed.isdecimal() or not denied.isdecimal() or allowed == denied:
            parser.error("dataset IDs must be distinct positive integers")
        check("query", "GET", f"{AGENT_QUERY_API}/dataset/{allowed}/dimension-members", {200})
        check("query", "GET", f"{AGENT_QUERY_API}/dataset/{denied}/dimension-members", {403})

    invalid_csrf = {"X-CSRFToken": "invalid-security-probe-token"}
    admin_only_write_probes = (
        ("POST", f"{SEMANTIC_API}/glossary/groups"),
        ("PUT", f"{SEMANTIC_API}/glossary/groups/0"),
        ("DELETE", f"{SEMANTIC_API}/glossary/groups/0"),
    )
    for role in ROLE_NAMES:
        for method, path in admin_only_write_probes:
            check(role, method, path, {403}, {}, invalid_csrf)
    for role in ("viewer", "query", "no_role"):
        csrf_header = {"X-CSRFToken": sessions[role][1]}
        for method, path in admin_only_write_probes:
            check(role, method, path, {403}, {}, csrf_header)

    if failures:
        raise SystemExit("\n".join(failures))
    print("Security probes passed. No authorized write request was sent.")


if __name__ == "__main__":
    main()
