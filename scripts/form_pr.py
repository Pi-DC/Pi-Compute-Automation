#!/usr/bin/env python3
"""Pull request steps of the firewall form jobs (jenkins/jobs/, stages 3, 4 and 6).

  form_pr.py open    --branch B --title T --body-file F --reviewers a,b   -> prints the PR number
  form_pr.py check   --pr N --require a,b --message M --merge-sha-file F
        exit 0  = merged now (or already merged); merge commit sha written to F
        exit 10 = waiting (build running, approvals missing, ...)
        exit 20 = rejected (changes requested, PR build failed, conflict, closed)
  form_pr.py comment --pr N --body-file F
  form_pr.py close   --pr N --body-file F        comment, close and delete the branch
  form_pr.py delete-branch --pr N                after a merge or revert

Env: GH_TOKEN, GITHUB_REPOSITORY. FW_APPROVERS defaults to the value in the Jenkinsfile.
"""
import argparse
import sys

from auto_merge import REPO, call, get, merge, pr_status


def names(csv):
    return [n.strip() for n in (csv or "").split(",") if n.strip()]


def pr_get(num):
    return get(f"/repos/{REPO}/pulls/{num}")[0]


def comment(num, path):
    with open(path) as f:
        ok, res = call("POST", f"/repos/{REPO}/issues/{num}/comments", {"body": f.read()})
    if not ok:
        print(f"WARNING: could not comment on PR #{num}: {res}")


def delete_branch(pr):
    ok, res = call("DELETE", f"/repos/{REPO}/git/refs/heads/{pr['head']['ref']}")
    print(f"Branch {pr['head']['ref']} deleted." if ok else f"WARNING: branch {pr['head']['ref']} not deleted: {res}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["open", "check", "comment", "close", "delete-branch"])
    ap.add_argument("--pr", type=int)
    ap.add_argument("--branch")
    ap.add_argument("--title")
    ap.add_argument("--body-file")
    ap.add_argument("--reviewers", default="")
    ap.add_argument("--require", default="")
    ap.add_argument("--message", default="")
    ap.add_argument("--merge-sha-file")
    a = ap.parse_args()

    if a.cmd == "open":
        with open(a.body_file) as f:
            ok, pr = call("POST", f"/repos/{REPO}/pulls", {"title": a.title, "head": a.branch, "base": "main", "body": f.read()})
        if not ok:
            sys.exit(f"ERROR: could not open the pull request: {pr}. The GitHub App needs 'Pull requests: Read and write'.")
        ok, res = call("POST", f"/repos/{REPO}/pulls/{pr['number']}/requested_reviewers", {"reviewers": names(a.reviewers)})
        if not ok:
            sys.exit(f"ERROR: PR #{pr['number']} opened ({pr['html_url']}), but requesting reviewers {names(a.reviewers)} failed: {res}. "
                     "Each reviewer must be a GitHub user with access to the repository.")
        print(pr["number"])
        return

    pr = pr_get(a.pr)
    if a.cmd == "check":
        state, msg = pr_status(pr, require=names(a.require))
        print(f"PR #{a.pr}: {state}, {msg}")
        if state == "ready":
            ok, res = merge(pr, a.message)
            if not ok:
                sys.exit(f"ERROR: merge failed: {res}")
            print(f"PR #{a.pr}: MERGED as {res[:7]}")
            sha = res
        elif state == "merged":
            sha = pr["merge_commit_sha"]
        elif state == "waiting":
            sys.exit(10)
        else:
            sys.exit(20)
        with open(a.merge_sha_file, "w") as f:
            f.write(sha + "\n")
    elif a.cmd == "comment":
        comment(a.pr, a.body_file)
    elif a.cmd == "close":
        comment(a.pr, a.body_file)
        if pr["state"] == "open":
            ok, res = call("PATCH", f"/repos/{REPO}/pulls/{a.pr}", {"state": "closed"})
            print(f"PR #{a.pr} closed." if ok else f"WARNING: PR #{a.pr} not closed: {res}")
        delete_branch(pr)
    elif a.cmd == "delete-branch":
        delete_branch(pr)


if __name__ == "__main__":
    main()
