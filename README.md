# Pi-Compute-Automation (Pi-DC)

OS firewall rules for client VMs, managed as code. Linux: UFW (Ubuntu) / firewalld (Red Hat, Rocky, AlmaLinux,
Oracle Linux, CentOS). Windows: Defender Firewall.

## How a change flows

1. Editor creates a branch, edits `host_vars/<host>.yml`, opens a Pull Request.
2. Jenkins builds the PR: lint, plan, firewall status, dry run. The plan shows exactly which rules are added/removed
   on which hosts; **Firewall status** shows whether each of those hosts has its firewall enabled and running.
3. Admin reviews and **Approves** the PR in GitHub. Jenkins job `Pi-PR-Auto-Merge` (started for this PR when its build passes) merges it within about 10 seconds
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
| `Pi-Linux-Systems-OSFW-Add` | Opens ports (adds rules) on a Linux client; adds the client if it is new (IP, name, OS, login, SSH port) |
| `Pi-Linux-Systems-OSFW-Remove` | Removes rules from a known Linux client (OS and SSH port come from the inventory) |
| `Pi-Windows-Systems-OSFW-Add` | Opens ports on a Windows client; adds the client if it is new (IP, name, OS, login) |
| `Pi-Windows-Systems-OSFW-Remove` | Removes rules from a known Windows client |

A Linux job refuses a Windows client and the other way round. **Build with Parameters**, fill in the form
(optionally more GitHub reviewers), click **Build**. Each job runs the same six stages:

1. **Request**: checks the form, writes the change to `inventory/hosts.yml` + `host_vars/<name>.yml`, lint, plan.
2. **Login**: logs in to the client with the given details (Linux: SSH + sudo, Windows: WinRM). Only if that
   works are they saved as Jenkins credential `client-<name>` (never in git). Reports the firewall status.
3. **Push and review**: dry run, pushes branch `form/<name>-<build>`, opens a PR and asks `Pi-KiranRaja`
   (plus the form's REVIEWERS) to review it.
4. **Approve and merge**: when the Jenkins PR build is green and every requested reviewer approved, Jenkins
   merges the PR within about 10 seconds (it checks every 10 s; Stage 3 starts the PR build at once). Changes requested, a failed PR build or no approval within 24 h: the PR is closed and
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
| `scripts/auto_merge.py`, `jenkins/pr-auto-merge.Jenkinsfile` | Job `Pi-PR-Auto-Merge`: one run per green PR, merges it right after the approval |
| `scripts/form_change.py` | Writes a Jenkins form request into the inventory and host_vars |
| `scripts/form_pr.py`, `scripts/rollback_plan.sh` | Form job: PR, reviewers, merge; old rules after a failed apply |
| `playbooks/login_check.yml` | Form job Stage 2: can Ansible log in? Changes nothing |
| `scripts/run-playbook.sh` | Runs a playbook on the given hosts, older systems with the older Ansible (below) |
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

## Supported Linux systems

Nothing is installed on a client, so Ansible uses the Python each system ships. ansible-core 2.21 needs Python
3.9+ there; `scripts/run-playbook.sh` runs older systems with ansible-core 2.16 from `/opt/ansible-el7` on
pi-jenkins-agent (collections pinned in `collections/requirements-el7.yml`) and that system's own Python:

| OS_TYPE / os_baseline | Firewall | Client Python | Ansible |
|---|---|---|---|
| CentOS-7, RedHat-7, OracleLinux-7 | firewalld | 2.7 `/usr/bin/python` | 2.16 |
| CentOS-8, RedHat-8, Rocky-8, AlmaLinux-8, OracleLinux-8 | firewalld | 3.6 `/usr/libexec/platform-python` | 2.16 |
| CentOS-9 (Stream), RedHat-9, Rocky-9, AlmaLinux-9, OracleLinux-9 | firewalld | 3.9 | 2.21 |
| CentOS-10 (Stream), RedHat-10, Rocky-10, AlmaLinux-10, OracleLinux-10 | firewalld | 3.12 | 2.21 |
| Ubuntu-20 | UFW | 3.8 | 2.16 |
| Ubuntu-22, Ubuntu-24, Ubuntu-26 | UFW | 3.10 / 3.12 / 3.13 | 2.21 |

The os_baseline must match what Ansible reports (`<distribution>-<major version>`); `playbooks/firewall.yml`
refuses a host whose real OS differs. Set up the older Ansible on the agent once:
`python3 -m venv /opt/ansible-el7 && /opt/ansible-el7/bin/pip install ansible-core==2.16.14 pyyaml`.
CentOS 7/8, RHEL 7, Oracle Linux 7 and Ubuntu 20.04 are past their standard support: replace them when you can.

## No default rules

No firewall rule is added by default, on Linux or Windows: a client gets exactly the rules in its
`host_vars/<host>.yml` (written by the Jenkins jobs) and `baselines/<OS>.yml` (empty). Because Ansible connects
from the Jenkins agent, `scripts/access_check.py` (run by Plan) stops any change that would leave a client
without a rule letting the agent `172.20.119.105` reach its SSH port (Linux) or WinRM 5986 (Windows); the
error shows the rule to add. Rules that earlier versions added on their own (SSH from 172.20.119.105 and
172.20.119.0/24; Windows `ANS-MGMT-WINRM` / `ANS-MGMT-RDP`) are removed from a client the next time it is applied.

## Nothing installed, no passwords kept

- Nothing is installed on a client, Linux or Windows: no software, no SSH keys. Ansible logs in with the
  username and password entered in the form (SSH + sudo, or WinRM). Lint (`scripts/no_package_installs.sh`)
  fails on any package or SSH-key task.
- No password is kept: not in git or GitHub, and not in Jenkins after a build. The form's login exists as
  the temporary credential `client-<name>` only while that build runs (its PR build uses it too) and is
  deleted at the end, whatever the result; the password parameter is blanked in the build record. Enter the
  login on every run. While one build uses a client's login, another build for that client stops in Stage 1.

Rollback: revert the PR in GitHub and merge the revert through the same approval.
