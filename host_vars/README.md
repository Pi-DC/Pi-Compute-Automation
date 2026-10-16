# host_vars

One file per client VM, named exactly like the host in `inventory/hosts.yml` (for example `client01.yml`).

```yaml
fw_rules:
  - {port: 443, proto: tcp, src: any, comment: "HTTPS"}
  - {port: 3306, proto: tcp, src: 172.20.120.0/24, comment: "MySQL from app subnet"}
  - {port: "8000-8010", proto: tcp, src: 172.20.120.15, comment: "App ports"}
```

| Field   | Values                          |
|---------|---------------------------------|
| port    | number, or range "start-end"    |
| proto   | tcp or udp                      |
| src     | any, an IP, or a CIDR           |
| dst     | optional: any (default), an IP or a CIDR on this host |
| comment | required: what the rule is for  |

- Add a line = open the port on this host only.
- Delete a line = close it on this host only.
- Edit a line = new rule added, old rule removed.
- No rule is added by default: list here every port the host needs open, including access for Jenkins.
  Plan refuses a change unless some rule lets the Jenkins agent 172.20.119.105 reach the host's SSH port
  (`fw_ssh_port` in `inventory/hosts.yml`, default 22) or, on Windows, WinRM 5986.
- Hosts added by the Jenkins form also carry `fw_cred_id` and read their login from `FWCRED_<HOST>_USER` /
  `FWCRED_<HOST>_PASS`, which the pipelines fill from that Jenkins credential. It exists only while a form
  job for that host runs (no password is kept in Jenkins), so change these hosts through the form jobs.
