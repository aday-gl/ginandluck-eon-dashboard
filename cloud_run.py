#!/usr/bin/env python3
"""
cloud_run.py — helper for the G&L EON dashboard scheduled task when it runs
in the cloud (no local folder). The GitHub repo is the source of truth.

Usage (token via env GH_TOKEN):
  python3 cloud_run.py pull  [--dest /tmp/eon]
      Downloads the repo tarball and extracts rebuild_dashboard.py,
      EON_Dashboard.html (template), index.html, and eon_data/*.json into dest.
  python3 cloud_run.py push  --workdir /tmp/eon --message "..." FILE [FILE ...]
      Pushes the given files (paths relative to workdir) in ONE commit via the
      Git Data API (blob -> tree -> commit -> ref), verifying each blob SHA.
  python3 cloud_run.py missing --workdir /tmp/eon [--days 7]
      Prints venues flagged missing:true in the last N days (skips dark days).
"""
import argparse, base64, hashlib, io, json, os, sys, tarfile, urllib.request

OWNER, REPO, BRANCH = "aday-gl", "ginandluck-eon-dashboard", "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
KEEP = ("rebuild_dashboard.py", "EON_Dashboard.html", "index.html", "eon_data/")


def headers():
    tok = os.environ.get("GH_TOKEN")
    if not tok:
        sys.exit("GH_TOKEN env var not set")
    return {"Authorization": f"token {tok}", "Accept": "application/vnd.github.v3+json",
            "User-Agent": "EON-Dashboard-Bot", "Content-Type": "application/json"}


def call(path, data=None, method=None, raw=False):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data else None,
                                 headers=headers(), method=method or ("POST" if data else "GET"))
    body = urllib.request.urlopen(req).read()
    return body if raw else json.loads(body)


def pull(dest):
    os.makedirs(dest, exist_ok=True)
    tgz = call(f"/tarball/{BRANCH}", raw=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tf:
        for m in tf.getmembers():
            rel = m.name.split("/", 1)[1] if "/" in m.name else ""
            if not rel or not m.isfile() or not rel.startswith(KEEP):
                continue
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(tf.extractfile(m).read())
            n += 1
    days = sorted(f[:-5] for f in os.listdir(os.path.join(dest, "eon_data")) if f.endswith(".json"))
    print(f"[pull] {n} files -> {dest}; {len(days)} day records; latest {days[-1] if days else 'n/a'}")


def push(workdir, files, message):
    head = call(f"/git/ref/heads/{BRANCH}")["object"]["sha"]
    base_tree = call(f"/git/commits/{head}")["tree"]["sha"]
    tree = []
    for rel in files:
        data = open(os.path.join(workdir, rel), "rb").read()
        b = call("/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        local = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        assert b["sha"] == local, f"SHA mismatch on {rel}"
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": b["sha"]})
    t = call("/git/trees", {"base_tree": base_tree, "tree": tree})
    c = call("/git/commits", {"message": message, "tree": t["sha"], "parents": [head]})
    call(f"/git/refs/heads/{BRANCH}", {"sha": c["sha"]}, method="PATCH")
    print(f"[push] commit {c['sha'][:8]} ({len(files)} files): {message}")
    return c["sha"]


def missing(workdir, days):
    import datetime
    d = os.path.join(workdir, "eon_data")
    today = datetime.date.today()
    out = []
    for i in range(1, days + 1):
        iso = (today - datetime.timedelta(days=i)).isoformat()
        p = os.path.join(d, iso + ".json")
        if not os.path.exists(p):
            out.append((iso, "<no file>"))
            continue
        for v in json.load(open(p))["venues"]:
            if v.get("missing"):
                narr = (v.get("narrative") or "").lower()
                if "dark day" in narr or "no service" in narr or "closed" in narr:
                    continue
                out.append((iso, v["id"]))
    for iso, vid in out:
        print(f"[missing] {iso} {vid}")
    if not out:
        print("[missing] none")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull"); p.add_argument("--dest", default="/tmp/eon")
    p = sub.add_parser("push"); p.add_argument("--workdir", default="/tmp/eon")
    p.add_argument("--message", required=True); p.add_argument("files", nargs="+")
    p = sub.add_parser("missing"); p.add_argument("--workdir", default="/tmp/eon"); p.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    if a.cmd == "pull":
        pull(a.dest)
    elif a.cmd == "push":
        push(a.workdir, a.files, a.message)
    else:
        missing(a.workdir, a.days)
