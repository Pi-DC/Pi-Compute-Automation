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
| comment | required: what the rule is for  |

- Add a line = open the port on this host only.
- Delete a line = close it on this host only.
- Edit a line = new rule added, old rule removed.
- SSH 22 / WinRM 5986 / RDP 3389 from the management network are protected and are not listed here.
