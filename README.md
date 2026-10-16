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

### Or: the Jenkins form (job `client-firewall-form`)

**Build with Parameters**, fill in the client (IP, name, OS, login, SSH/RDP port) and the rules to add or
remove, click **Build**. The job saves the login as Jenkins credential `client-<name>` (never in git),
commits the change to `inventory/hosts.yml` + `host_vars/<name>.yml`, lints, plans and dry-runs it, then
waits for `Pi-Compute` to click **Apply**. Only then does it push the commit to `main` (trailer
`Fw-Form-Build:`), apply it to that one client and tag `deployed-form-<build>`. The `main` build skips
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
| `scripts/form_change.py` | Writes a Jenkins form request into the inventory and host_vars |
| `jenkins/client-firewall-form.groovy` | Pipeline of the `client-firewall-form` job |
| `roles/` | Linux UFW, Linux firewalld, Windows firewall |

## Rule format

```yaml
fw_rules:
  - {port: 443, proto: tcp, src: any, comment: "HTTPS"}
  - {port: 8443, proto: tcp, src: 172.20.120.0/24, dst: 172.20.119.111, comment: "Admin UI on one address"}
```

`dst` (optional, default `any`) limits the rule to one destination address of the client.

Rollback: revert the PR in GitHub and merge the revert through the same approval.
