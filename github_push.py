#!/usr/bin/env python3
"""
Direct GitHub API push — no git CLI, no lock files, no dependencies.
Run with: python3 github_push.py
"""
import json, base64, os, sys, urllib.request, urllib.error

TOKEN = "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"
OWNER = "aday-gl"
REPO  = "ginandluck-eon-dashboard"
BASE  = f"https://api.github.com/repos/{OWNER}/{REPO}/contents"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_TO_PUSH = (
    ["EON_Dashboard.html", "index.html"] +
    [f"eon_data/2026-03-{d:02d}.json" for d in range(15, 32)] +
    ["eon_data/2026-04-01.json"]
)

def api(method, path, data=None):
    url = f"{BASE}/{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}

def push_file(rel_path):
    local_path = os.path.join(SCRIPT_DIR, rel_path)
    if not os.path.exists(local_path):
        return None
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    # Get current SHA
    status, info = api("GET", rel_path)
    sha = info.get("sha") if status == 200 else None
    payload = {
        "message": "Fix missing venues Mar 15-29 + regenerate dashboard",
        "content": content
    }
    if sha:
        payload["sha"] = sha
    status, _ = api("PUT", rel_path, payload)
    return status

print("Pushing EON Dashboard to GitHub...")
print("=" * 52)
success, fail = 0, 0
for fpath in FILES_TO_PUSH:
    status = push_file(fpath)
    if status is None:
        print(f"  - SKIP : {fpath}")
        continue
    ok = status in (200, 201)
    print(f"  {'✓' if ok else '✗'} [{status}] {fpath}")
    if ok:
        success += 1
    else:
        fail += 1

print("=" * 52)
if fail == 0:
    print(f"✓ All {success} files pushed successfully!")
    print(f"  Live in ~60s: https://aday-gl.github.io/ginandluck-eon-dashboard/EON_Dashboard.html")
else:
    print(f"  {success} OK, {fail} FAILED")
    sys.exit(1)
