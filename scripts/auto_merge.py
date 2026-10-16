#!/usr/bin/env python3
"""Merge open pull requests that are ready. Run by the Jenkins job pr-auto-merge every 2 minutes.

A PR is ready (pr_status) only when all of these hold:
  1. it targets main, comes from a branch of this repo (no forks) and is not a draft,
  2. the Jenkins PR build of its final commit is SUCCESS (GitHub status continuous-integration/jenkins/pr-merge),
  3. it is approved on that final commit by someone in FW_APPROVERS who is not its author, and nobody has
     an open "changes requested" (the same rule as approval_check.py, which checks it again before Apply),
     and every reviewer in `require` approved that commit too,
  4. GitHub can merge it without conflicts.
The merge is pinned to the checked commit, so a push after the checks is not merged. Merging changes no
firewall: the main build still waits for the Apply click.
Branches form/* belong to the firewall form jobs (jenkins/jobs/), which merge and apply them themselves.

Env: GH_TOKEN, GITHUB_REPOSITORY (org/repo). FW_APPROVERS defaults to the value in the Jenkinsfile.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

if not os.environ.get("FW_APPROVERS"):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Jenkinsfile")) as f:
        os.environ["FW_APPROVERS"] = re.search(r"def FW_APPROVERS\s*=\s*'([^']*)'", f.read()).group(1)

from approval_check import API, APPROVERS, REPO, get, review_state  # noqa: E402

BUILD_CONTEXT = "continuous-integration/jenkins/pr-merge"


def call(method, path, body=None):
    """GitHub API call; returns (ok, parsed JSON or error message)."""
    req = urllib.request.Request(
        f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            msg = json.loads(raw).get("message", "")
        except ValueError:
            msg = raw.decode(errors="replace")[:200]
        return False, f"HTTP {e.code}: {msg}"


def pr_status(pr, require=()):
    """(state, message). state: merged | closed | rejected | waiting | ready."""
    num, author, head = pr["number"], pr["user"]["login"].lower(), pr["head"]["sha"]
    if pr.get("merged_at"):
        return "merged", f"already merged as {pr['merge_commit_sha'][:7]}"
    if pr["state"] != "open":
        return "closed", "closed without merging"
    if pr["draft"] or pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != REPO:
        return "waiting", "draft or from a fork: not merged automatically"

    statuses = get(f"/repos/{REPO}/commits/{head}/statuses")
    build = next((s["state"] for s in statuses if s["context"] == BUILD_CONTEXT), None)  # newest first
    if build in ("failure", "error"):
        return "rejected", f"Jenkins PR build of {head[:7]} is {build.upper()}"
    if build != "success":
        return "waiting", f"Jenkins PR build of {head[:7]} is {build or 'not reported yet'}"

    valid, blocked, approved = review_state(num, author, head, with_all=True)
    if blocked:
        return "rejected", f"changes requested by {blocked}"
    if not valid:
        return "waiting", f"needs an approval on {head[:7]} from one of {sorted(APPROVERS)} (not the author)"
    missing = sorted({r.lower() for r in require} - approved)
    if missing:
        return "waiting", f"approved by {sorted(approved)}; still waiting for {missing}"

    mergeable = get(f"/repos/{REPO}/pulls/{num}")[0].get("mergeable")
    if mergeable is False:
        return "rejected", "merge conflict with main"
    if mergeable is not True:
        return "waiting", "GitHub is still checking whether it can be merged"
    return "ready", f"build SUCCESS, approved by {sorted(approved)}"


def merge(pr, message):
    """Merge pinned to the checked commit. Returns (ok, merge sha or error)."""
    ok, res = call("PUT", f"/repos/{REPO}/pulls/{pr['number']}/merge", {
        "sha": pr["head"]["sha"], "merge_method": "merge",
        "commit_title": f"Merge pull request #{pr['number']}: {pr['title']}", "commit_message": message})
    return ok, (res.get("sha") if ok else res)


def main():
    failed = False
    prs = get(f"/repos/{REPO}/pulls?state=open&base=main")
    if not prs:
        print("No open pull requests.")
    for pr in prs:
        tag = f"PR #{pr['number']} ({pr['head']['ref']} @ {pr['head']['sha'][:7]}, by {pr['user']['login']})"
        if pr["head"]["ref"].startswith("form/"):
            print(f"{tag}: skipped, its firewall form job merges and applies it")
            continue
        state, msg = pr_status(pr)
        if state != "ready":
            print(f"{tag}: {state}, {msg}")
            continue
        ok, res = merge(pr, f"Merged by Jenkins pr-auto-merge: {msg}.")
        if ok:
            print(f"{tag}: MERGED as {res[:7]} ({msg})")
        else:
            print(f"{tag}: merge FAILED: {res}")
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
