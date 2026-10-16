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
   on any of those hosts where it is off, after first allowing the protected management access. Then stage
   **Update firewall rules**: Ansible changes only the changed rules on only the changed hosts.
6. Jenkins tags the commit `deployed-<build>` = what is live.

Direct pushes to `main` are refused by Jenkins (GitHub Free cannot block them for private repos).

### Or: the Jenkins form (job `client-firewall-form`)

**Build with Parameters**, fill in the client (IP, name, OS, login, SSH/RDP port) and the rules to add or
remove, click **Build**. The job saves the login as Jenkins credential `client-<name>` (never in git),
commits the change to `inventory/hosts.yml` + `host_vars/<name>.yml`, lints, plans, checks the firewall status
and dry-runs it, then waits for `Pi-Compute` to click **Apply**. Only then does it enable + start the client's
firewall if it is off, push the commit to `main` (trailer `Fw-Form-Build:`), apply the rules to that one client
and tag `deployed-form-<build>`. The `main` build skips
commits with that trailer, because the form job already approved and applied them. See `jenkins/README.md`.

## Layout

| Path | What it is |
|---|---|
| `inventory/hosts.yml` | Client VMs: IP + `os_baseline` |
| `host_vars/<host>.yml` | That host's rules (day-to-day changes) |
| `baselines/<OS>.yml` | Rules for every host of that OS version |
| `inventory/group_vars/all.yml` | Management IPs that are always allowed |
| `scripts/plan.sh`, `scripts/fw_diff.py` | Work out adds/removes since the last deploy |
| `scripts/approval_check.py` | Refuses to apply unapproved changes |
| `scripts/auto_merge.py`, `jenkins/pr-auto-merge.Jenkinsfile` | Job `pr-auto-merge`: merges green + approved PRs |
| `scripts/form_change.py` | Writes a Jenkins form request into the inventory and host_vars |
| `scripts/run-playbook.sh` | Runs a playbook on the given hosts; CentOS 7 hosts with the older Ansible (below) |
| `jenkins/client-firewall-form.groovy` | Pipeline of the `client-firewall-form` job |
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

Rollback: revert the PR in GitHub and merge the revert through the same approval.
