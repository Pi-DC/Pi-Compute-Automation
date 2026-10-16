# Jenkins jobs

| Job | Defined by | What it does |
|---|---|---|
| `os-firewall` (multibranch) | `Jenkinsfile` | PRs: lint, plan, dry run. `main`: approval check, Apply, tag `deployed-N` |
| `client-firewall-form` | `client-firewall-form.groovy` (stored in the job) | Form: add/change one client and its rules, Apply, tag `deployed-form-N` |

`client-firewall-form` runs its pipeline from the job configuration, not from git, because saving the
client login as a Jenkins credential needs the Jenkins API (not allowed in the Groovy sandbox). Only Jenkins
admins can change it, and Jenkins asks an admin to approve the script after every change
(Manage Jenkins > In-process Script Approval).

To change the job: edit `client-firewall-form.groovy` through a pull request, then after the merge paste it
into the job (Configure > Pipeline > Script) or update the job's `config.xml` with the Jenkins CLI
(`update-job client-firewall-form`), and approve the script.

## Form rule format

One rule per line in **RULES_ADD** / **RULES_REMOVE**:

```
SOURCE  DESTINATION  PORTS  [tcp|udp]  [comment]
172.20.120.0/24  any             80,443     tcp  Web from app subnet
any              172.20.119.111  8000-8010  udp  App ports
```

SOURCE / DESTINATION: `any`, an IP or a CIDR. PORTS: `443`, `8000-8010` or `80,443`. A rule to remove must
match an existing rule's source, destination, port and protocol.
