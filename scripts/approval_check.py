#!/usr/bin/env python3
"""Pre-apply check (GitHub Free: GitHub cannot enforce PR approval, so Jenkins does).

Refuses to apply unless the commit being deployed:
  1. came from a merged pull request (a direct push to main is refused), and
  2. that PR was approved, on its final commit, by someone in FW_APPROVERS who is not the PR author,
  3. and nobody has an open "changes requested" review.

Env: GH_TOKEN, GITHUB_REPOSITORY (org/repo), COMMIT_SHA, FW_APPROVERS (comma-separated GitHub logins).
"""
import json
import os
import sys
import urllib.request

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
APPROVERS = {a.strip().lower() for a in os.environ["FW_APPROVERS"].split(",") if a.strip()}


def get(path):
    out, url = [], f"{API}{path}{'&' if '?' in path else '?'}per_page=100"
    while url:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req) as r:
            data = json.load(r)
            out += data if isinstance(data, list) else [data]
            nxt = [l.split(";")[0].strip(" <>") for l in r.headers.get("Link", "").split(",") if 'rel="next"' in l]
            url = nxt[0] if nxt else None
    return out


def review_state(num, author, head):
    """(approvers who approved commit `head` of PR `num`, users with an open "changes requested")."""
    latest = {}
    for r in get(f"/repos/{REPO}/pulls/{num}/reviews"):
        if r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[r["user"]["login"].lower()] = (r["state"], r.get("commit_id"))
    valid = {u for u, (s, c) in latest.items() if s == "APPROVED" and c == head and u != author and u in APPROVERS}
    blocked = [u for u, (s, _) in latest.items() if s == "CHANGES_REQUESTED"]
    return valid, blocked


def main():
    merged = [p for p in get(f"/repos/{REPO}/commits/{os.environ['COMMIT_SHA']}/pulls") if p.get("merged_at")]
    if not merged:
        sys.exit("REFUSED: this commit was pushed directly to main, not merged from an approved pull request.")
    pr = merged[0]
    num, author, head = pr["number"], pr["user"]["login"].lower(), pr["head"]["sha"]
    valid, blocked = review_state(num, author, head)

    print(f"PR #{num} by {author}; approved on final commit by: {sorted(valid) or 'nobody'}")
    if blocked:
        sys.exit(f"REFUSED: changes requested by {blocked}.")
    if not valid:
        sys.exit(f"REFUSED: PR #{num} needs an approval on its final commit from one of {sorted(APPROVERS)} (not the author).")
    print("Approval check PASSED")


if __name__ == "__main__":
    main()
