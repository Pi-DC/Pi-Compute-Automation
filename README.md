# os-firewall-automation (Pi-DC)

OS firewall rules for client VMs, managed as code. Linux: UFW (Ubuntu) / firewalld (RHEL, CentOS 7). Windows: Defender Firewall.

## How a change flows

1. Editor creates a branch, edits `host_vars/<host>.yml`, opens a Pull Request.
2. Jenkins builds the PR: lint, plan, firewall status, dry run. The plan shows exactly which rules are added/removed
   on which hosts; **Firewall status** shows whether each of those hosts has its firewall enabled and running.
3. Admin reviews and **Approves** the PR in GitHub. Jenkins job `pr-auto-merge` merges it within ~2 minutes
   once its PR build is green and it is approved on its final commit (the admin can also merge it by hand).
   The approver cannot be the PR author (GitHub does not allow approving your own PR).
4. Jenkins builds `main`: checks the commit came from a PR the admin approved, then waits.
5. Admin clicks **Apply** in Jenkins. Stage **Enable firewall** switches the firewall on (enabled at boot + running)
   on any of those hosts where it is off, with that host's own rules already in place. Then stage
   **Update firewall rules**: Ansible changes only the changed rules on only the changed hosts.
6. Jenkins tags the commit `deployed-<build>` = what is live.

Direct pushes to `main` are refused by Jenkins (GitHub Free cannot block them for private repos).

### Or: the Jenkins form jobs

| Job | What it does |
|---|---|
| `Linux-Firewall-Ports-Open` | Opens ports (adds rules) on a Linux client; adds the client if it is new (IP, name, OS, login, SSH port) |
| `Linux-Firewall-Ports-Remove` | Removes rules from a known Linux client (OS and SSH port come from the inventory) |
| `Windows-Firewall-Open` | Opens ports on a Windows client; adds the client if it is new (IP, name, OS, login, RDP port) |
| `Windows-Firewall-Remove` | Removes rules from a known Windows client |

A Linux job refuses a Windows client and the other way round. **Build with Parameters**, fill in the form
(optionally more GitHub reviewers), click **Build**. Each job runs the same six stages:

1. **Request**: checks the form, writes the change to `inventory/hosts.yml` + `host_vars/<name>.yml`, lint, plan.
2. **Login**: logs in to the client with the given details (Linux: SSH + sudo, Windows: WinRM). Only if that
   works are they saved as Jenkins credential `client-<name>` (never in git). Reports the firewall status.
3. **Push and review**: dry run, pushes branch `form/<name>-<build>`, opens a PR and asks `Pi-KiranRaja`
   (plus the form's REVIEWERS) to review it.
4. **Approve and merge**: when the Jenkins PR build is green and every requested reviewer approved, Jenkins
   merges the PR. Changes requested, a failed PR build or no approval within 24 h: the PR is closed and
   nothing is applied.
5. **Apply**: enables + starts the client's firewall if it is off, applies the rules, tags `deployed-form-<build>`.
6. **Result**: success, or if Stage 5 failed, Jenkins reverts the merge on `main` and applies the old rules
   again (the firewall stays enabled), comments on the PR and fails the build.

The `main` build skips commits with the trailer `Fw-Form-Build:`, because the form job applies them. See `jenkins/README.md`.

## Layout

| Path | What it is |
|---|---|
| `inventory/hosts.yml` | Client VMs: IP + `os_baseline` |
| `host_vars/<host>.yml` | That host's rules (day-to-day changes) |
| `baselines/<OS>.yml` | Rules for every host of that OS version |
| `inventory/group_vars/all.yml` | Jenkins agent IP (whose access `scripts/access_check.py` checks); no default rules |
| `scripts/plan.sh`, `scripts/fw_diff.py` | Work out adds/removes since the last deploy |
| `scripts/approval_check.py` | Refuses to apply unapproved changes |
| `scripts/auto_merge.py`, `jenkins/pr-auto-merge.Jenkinsfile` | Job `pr-auto-merge`: merges green + approved PRs |
| `scripts/form_change.py` | Writes a Jenkins form request into the inventory and host_vars |
| `scripts/form_pr.py`, `scripts/rollback_plan.sh` | Form job: PR, reviewers, merge; old rules after a failed apply |
| `playbooks/login_check.yml` | Form job Stage 2: can Ansible log in? Changes nothing |
| `scripts/run-playbook.sh` | Runs a playbook on the given hosts; CentOS 7 hosts with the older Ansible (below) |
| `jenkins/firewall-form-template.groovy`, `jenkins/jobs/` | Pipelines of the four form jobs: `scripts/form_jobs.py` generates `jobs/` from the template |
| `playbooks/firewall.yml` | Applies the planned rule changes |
| `playbooks/firewall_service.yml` | Checks (`fw_service_mode=check`) or enables + starts (`ensure`) the firewall itself |
| `roles/` | Linux UFW, Linux firewalld, Windows firewall rules; `fw_service`: firewall on/off |

## Rule format

```yaml
fw_rules:
  - {port: 443, proto: tcp, src: any, comment: "HTTPS"}
  - {port: 8443, proto: tcp, src: 172.20.120.0/24, dst: 172.20.119.111, comment: "Admin UI on one address"}
```

`dst` (optional, default `any`) limits the rule to one destination address of the client.

## CentOS 7 hosts

CentOS 7 has only Python 2.7, which ansible-core 2.17 and later cannot manage. `scripts/run-playbook.sh`
runs hosts with `os_baseline: CentOS-7` with ansible-core 2.16 from `/opt/ansible-el7` on pi-jenkins-agent,
the collections pinned in `collections/requirements-el7.yml` and `/usr/bin/python` (it has the firewalld
bindings). All other hosts use the normal Ansible. Lint always runs with the normal Ansible.

Set up on the agent once: `python3 -m venv /opt/ansible-el7 && /opt/ansible-el7/bin/pip install ansible-core==2.16.14 pyyaml`.
CentOS 7 is end-of-life (no security updates since June 2024): replace these hosts when you can, then
delete the venv, this section, the wrapper's legacy branch and `requirements-el7.yml`.

## No default rules

No firewall rule is added by default, on Linux or Windows: a client gets exactly the rules in its
`host_vars/<host>.yml` (written by the Jenkins jobs) and `baselines/<OS>.yml` (empty). Because Ansible connects
from the Jenkins agent, `scripts/access_check.py` (run by Plan) stops any change that would leave a client
without a rule letting the agent `172.20.119.105` reach its SSH port (Linux) or WinRM 5986 (Windows); the
error shows the rule to add. Rules that earlier versions added on their own (SSH from 172.20.119.105 and
172.20.119.0/24; Windows `ANS-MGMT-WINRM` / `ANS-MGMT-RDP`) are removed from a client the next time it is applied.

Rollback: revert the PR in GitHub and merge the revert through the same approval.
