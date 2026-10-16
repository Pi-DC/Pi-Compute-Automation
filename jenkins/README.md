# Jenkins jobs

| Job | Defined by | What it does |
|---|---|---|
| `os-firewall` (multibranch) | `Jenkinsfile` | PRs: lint, plan, firewall status, dry run. `main`: firewall status, approval check, Apply, enable firewall, update rules, tag `deployed-N` |
| `pr-auto-merge` | `pr-auto-merge.Jenkinsfile` (Pipeline from SCM, main) | Every 2 min: merges open PRs whose Jenkins PR build is SUCCESS and that an approver approved on the final commit. Applies nothing |
| `client-firewall-form` | `client-firewall-form.groovy` (stored in the job) | Form, 6 stages: request, login check, push + PR with reviewers, approval + merge, apply, result (rollback on failure) |

Both jobs check the firewall on the hosts they change before touching rules. If it is disabled or stopped
(UFW inactive, firewalld stopped/masked, Windows MpsSvc stopped or a profile off), stage **Enable firewall**
allows the protected management access (SSH / WinRM / RDP), enables the firewall at boot and starts it, and
fails the build before any rule change if that does not work.

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
