#!/usr/bin/env python3
"""Merge open pull requests that are ready. Run by the Jenkins job pr-auto-merge every 2 minutes.

A PR is merged only when all of these hold:
  1. it targets main, comes from a branch of this repo (no forks) and is not a draft,
  2. the Jenkins PR build of its final commit is SUCCESS (GitHub status continuous-integration/jenkins/pr-merge),
  3. it is approved on that final commit by someone in FW_APPROVERS who is not its author, and nobody has
     an open "changes requested" (the same rule as approval_check.py, which checks it again before Apply),
  4. GitHub can merge it without conflicts.
The merge is pinned to the checked commit, so a push after the checks is not merged. Merging changes no
firewall: the main build still waits for the Apply click.

Env: GH_TOKEN, GITHUB_REPOSITORY (org/repo). FW_APPROVERS defaults to the value in the Jenkinsfile.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

if not os.environ.get("FW_APPROVERS"):
    with open("Jenkinsfile") as f:
        os.environ["FW_APPROVERS"] = re.search(r"def FW_APPROVERS\s*=\s*'([^']*)'", f.read()).group(1)

from approval_check import API, APPROVERS, REPO, get, review_state  # noqa: E402

BUILD_CONTEXT = "continuous-integration/jenkins/pr-merge"


def merge(num, sha, title):
    req = urllib.request.Request(
        f"{API}/repos/{REPO}/pulls/{num}/merge", method="PUT",
        data=json.dumps({"sha": sha, "merge_method": "merge",
                         "commit_title": f"Merge pull request #{num}: {title}",
                         "commit_message": "Merged by Jenkins pr-auto-merge: build SUCCESS and approved."}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req) as r:
            return True, json.load(r).get("sha")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {json.loads(e.read() or b'{}').get('message', '')}"


def main():
    failed = False
    prs = get(f"/repos/{REPO}/pulls?state=open&base=main")
    if not prs:
        print("No open pull requests.")
    for pr in prs:
        num, author, head = pr["number"], pr["user"]["login"].lower(), pr["head"]["sha"]
        tag = f"PR #{num} ({pr['head']['ref']} @ {head[:7]}, by {author})"
        if pr["draft"] or pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != REPO:
            print(f"{tag}: skipped (draft or from a fork)")
            continue

        statuses = get(f"/repos/{REPO}/commits/{head}/statuses")
        build = next((s["state"] for s in statuses if s["context"] == BUILD_CONTEXT), None)  # newest first
        if build != "success":
            print(f"{tag}: waiting, Jenkins PR build is {build or 'not reported yet'}")
            continue

        valid, blocked = review_state(num, author, head)
        if blocked:
            print(f"{tag}: waiting, changes requested by {blocked}")
            continue
        if not valid:
            print(f"{tag}: waiting, needs an approval on {head[:7]} from one of {sorted(APPROVERS)} (not the author)")
            continue

        mergeable = get(f"/repos/{REPO}/pulls/{num}")[0].get("mergeable")
        if mergeable is not True:
            print(f"{tag}: waiting, GitHub says mergeable={mergeable} (conflict, or still computing)")
            continue

        ok, result = merge(num, head, pr["title"])
        if ok:
            print(f"{tag}: MERGED as {result[:7]} (build SUCCESS, approved by {sorted(valid)})")
        else:
            print(f"{tag}: merge FAILED: {result}")
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
