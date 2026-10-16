# os-firewall-automation (Pi-DC)

OS firewall rules for client VMs, managed as code. Linux: UFW (Ubuntu) / firewalld (RHEL). Windows: Defender Firewall.

## How a change flows

1. Editor creates a branch, edits `host_vars/<host>.yml`, opens a Pull Request.
2. Jenkins builds the PR: lint, plan, dry run. The plan shows exactly which rules are added/removed on which hosts.
3. Admin reviews and **Approves** the PR in GitHub, then merges it.
4. Jenkins builds `main`: checks the commit came from a PR the admin approved, then waits.
5. Admin clicks **Apply** in Jenkins. Ansible changes only the changed rules on only the changed hosts.
6. Jenkins tags the commit `deployed-<build>` = what is live.

Direct pushes to `main` are refused by Jenkins (GitHub Free cannot block them for private repos).

## Layout

| Path | What it is |
|---|---|
| `inventory/hosts.yml` | Client VMs: IP + `os_baseline` |
| `host_vars/<host>.yml` | That host's rules (day-to-day changes) |
| `baselines/<OS>.yml` | Rules for every host of that OS version |
| `inventory/group_vars/all.yml` | Management IPs that are always allowed |
| `scripts/plan.sh`, `scripts/fw_diff.py` | Work out adds/removes since the last deploy |
| `scripts/approval_check.py` | Refuses to apply unapproved changes |
| `roles/` | Linux UFW, Linux firewalld, Windows firewall |

## Rule format

```yaml
fw_rules:
  - {port: 443, proto: tcp, src: any, comment: "HTTPS"}
```

Rollback: revert the PR in GitHub and merge the revert through the same approval.
