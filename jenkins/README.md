# Jenkins jobs

| Job | Defined by | What it does |
|---|---|---|
| `os-firewall` (multibranch) | `Jenkinsfile` | PRs: lint, plan, firewall status, dry run. `main`: firewall status, approval check, Apply, enable firewall, update rules, tag `deployed-N` |
| `pr-auto-merge` | `pr-auto-merge.Jenkinsfile` (Pipeline from SCM, main) | Every minute: merges open PRs whose Jenkins PR build is SUCCESS and that an approver approved on the final commit. Applies nothing |
| `Linux-Firewall-Ports-Open`, `Linux-Firewall-Ports-Remove`, `Windows-Firewall-Open`, `Windows-Firewall-Remove` | `jobs/<job>.groovy` (stored in the job) | Forms, 6 stages each: request, login check, push + PR with reviewers, approval + merge, apply, result (rollback on failure) |

Both jobs check the firewall on the hosts they change before touching rules. If it is disabled or stopped
(UFW inactive, firewalld stopped/masked, Windows MpsSvc stopped or a profile off), stage **Enable firewall**
first adds the client's own rules, then enables the firewall at boot and starts it, and fails the build
before any rule change if that does not work. No rule is added by default.

The form jobs run their pipelines from the job configuration, not from git, because saving the client login
as a Jenkins credential needs the Jenkins API (not allowed in the Groovy sandbox). Only Jenkins admins can
change them, and Jenkins asks an admin to approve each script after every change
(Manage Jenkins > In-process Script Approval). Loading Groovy from git at run time would let anyone who can
merge to main run code as Jenkins, so the scripts are copied into the jobs instead.

The four scripts are generated from `firewall-form-template.groovy` (only the form fields and the
family/action settings differ). To change them:

1. Edit the template (or `JOBS` / `params()` in `scripts/form_jobs.py`), run `python3 scripts/form_jobs.py`,
   commit the template and `jobs/` through a pull request (Lint fails if `jobs/` is out of date).
   Before that, check they compile as pipeline code: `java -jar jenkins-cli.jar ... groovy = < jenkins/cps-compile-check.groovy`
   (the declarative validator alone misses e.g. the spread operator `*.`, which pipelines do not support).
2. After the merge, for each job: `python3 scripts/form_jobs.py --config-xml <job> | java -jar jenkins-cli.jar ... update-job <job>`
   (`create-job` for a new one), then approve the script.

## Form rule format

One rule per line in **RULES_ADD** / **RULES_REMOVE**:

```
SOURCE  DESTINATION  PORTS  [tcp|udp]  [comment]
172.20.120.0/24  any             80,443     tcp  Web from app subnet
any              172.20.119.111  8000-8010  udp  App ports
```

SOURCE / DESTINATION: `any`, an IP or a CIDR. PORTS: `443`, `8000-8010` or `80,443`. A rule to remove must
match an existing rule's source, destination, port and protocol.
