// @@HEADER@@
//
// GENERATED from jenkins/firewall-form-template.groovy by scripts/form_jobs.py: edit the template, run
// `python3 scripts/form_jobs.py`, commit both. This script is the job's own (admin-approved, not sandboxed)
// pipeline: saving a credential needs the Jenkins API. jenkins/README.md says how to update the job.
//
//   Stage 1 - Request          check the form, write the change (inventory + host_vars), lint, plan
//   Stage 2 - Login            log in to the client (Linux: SSH + sudo, Windows: WinRM); only then save new
//                              login details as Jenkins credential client-<name>; report the firewall status
//   Stage 3 - Push and review  dry run, push branch form/<job>-<name>-<build>, open a PR, request review
//                              from REVIEWER (+ the form's REVIEWERS)
//   Stage 4 - Approve, merge   wait (without holding the agent) until the Jenkins PR build is SUCCESS and
//                              every requested reviewer approved, then merge to main. Changes requested,
//                              failed PR build or no approval in 24 h: close the PR, nothing is applied
//   Stage 5 - Apply            enable + start the firewall if it is off, apply the rules, tag deployed-<job>-<build>
//   Stage 6 - Result           success, or if Stage 5 failed: revert the merge on main and apply the old
//                              rules again (the firewall stays enabled), then fail the build
import com.cloudbees.plugins.credentials.CredentialsProvider
import com.cloudbees.plugins.credentials.CredentialsScope
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.common.StandardUsernamePasswordCredentials
import com.cloudbees.plugins.credentials.domains.Domain
import com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl
import hudson.security.ACL
import jenkins.model.Jenkins

def REPO       = 'Pi-DC/os-firewall-automation'
def REPO_URL   = "https://github.com/${REPO}.git"
def REVIEWER   = 'Pi-KiranRaja'   // always asked to review; must be in FW_APPROVERS in the Jenkinsfile
def REVIEW_HOURS = 24
def JOB_FAMILY = '@@FAMILY@@'   // linux | windows: clients of the other family are refused
def JOB_ACTION = '@@ACTION@@'   // open: RULES_ADD only | remove: RULES_REMOVE only, known clients only
def JOB_SLUG   = '@@SLUG@@'     // in branch, tag and credential names, unique per job

@NonCPS
def findLogin(String id) {
  CredentialsProvider.lookupCredentials(StandardUsernamePasswordCredentials, Jenkins.get(), ACL.SYSTEM, [])
    .find { it.id == id }
}

@NonCPS
def saveLogin(String id, String user, String pass, String desc) {
  def store = SystemCredentialsProvider.getInstance().getStore()
  def c = new UsernamePasswordCredentialsImpl(CredentialsScope.GLOBAL, id, desc, user, pass)
  def old = findLogin(id)
  old ? store.updateCredentials(Domain.global(), old, c) : store.addCredentials(Domain.global(), c)
  return old ? 'updated' : 'created'
}

@NonCPS
def deleteLogin(String id) {
  def old = findLogin(id)
  if (old) { SystemCredentialsProvider.getInstance().getStore().removeCredentials(Domain.global(), old) }
}

@NonCPS
def plainText(value) {
  value instanceof hudson.util.Secret ? value.getPlainText() : (value ?: '').toString()
}

def gitAuth(String cmd) {
  withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
    sh 'set +x; git -c http.extraHeader="Authorization: Basic $(printf \'x-access-token:%s\' "$GH_TOKEN" | base64 -w0)" ' + cmd
  }
}

def withGitHub(String repo, Closure body) {
  withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
    withEnv(["GITHUB_REPOSITORY=${repo}"]) { body() }
  }
}

// The client's login is bound to FWCRED_<NAME>_USER/_PASS, which the inventory reads.
// env.FW_LOGIN_ID is the credential to use: a pending one while Stage 2 tests new details.
def withClientCreds(Closure body) {
  withCredentials([
    sshUserPrivateKey(credentialsId: 'ansible-ssh-key', keyFileVariable: 'SSH_KEY'),
    usernamePassword(credentialsId: 'ansible-win-cred', usernameVariable: 'WIN_USER', passwordVariable: 'WIN_PASS'),
    usernamePassword(credentialsId: env.FW_LOGIN_ID, usernameVariable: "${env.FW_CRED_ENV}_USER", passwordVariable: "${env.FW_CRED_ENV}_PASS")
  ]) { body() }
}

pipeline {
  agent none
  options {
    timestamps()
    ansiColor('xterm')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(daysToKeepStr: '365'))
  }
  parameters {
@@PARAMETERS@@
  }
  stages {
    stage('Stage 1 - Request') {
      agent { label 'ansible' }
      steps {
        script {
          def ip = params.CLIENT_IP ?: ''
          if (!(ip ==~ /\d{1,3}(\.\d{1,3}){3}/)) { error "CLIENT_IP '${ip}' is not an IPv4 address" }
          def name = (params.CLIENT_NAME ?: "client-${ip.replace('.', '-')}").toLowerCase()
          if (!(name ==~ /[a-z0-9][a-z0-9-]{0,62}/)) { error "CLIENT_NAME '${name}': use lowercase letters, digits and '-'" }
          env.FW_NAME = name
          env.FW_IP = ip
          env.FW_IS_LINUX = JOB_FAMILY == 'linux' ? 'yes' : ''
          env.FW_CRED_ID = "client-${name}"
          env.FW_CRED_ENV = 'FWCRED_' + name.toUpperCase().replaceAll('[^A-Z0-9]', '_')
          def causes = currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause')
          env.FW_REQUESTER = causes ? causes[0].userId : 'unknown'

          def reviewers = [REVIEWER]
          for (r in (params.REVIEWERS ?: '').tokenize(', ')) {
            if (!(r ==~ /[A-Za-z0-9](-?[A-Za-z0-9]){0,38}/)) { error "REVIEWERS: '${r}' is not a GitHub user name" }
            if (!reviewers*.toLowerCase().contains(r.toLowerCase())) { reviewers << r }
          }
          env.FW_REVIEWERS = reviewers.join(',')

          def user = params.CLIENT_USERNAME ?: ''
          def pass = plainText(params.CLIENT_PASSWORD)
          if (pass && !user) { error 'Enter CLIENT_USERNAME together with CLIENT_PASSWORD' }
          if (user && !pass) { error 'CLIENT_USERNAME given without CLIENT_PASSWORD: enter both to change the saved login, or neither to keep it' }
          if (!pass && !findLogin(env.FW_CRED_ID)) { error "No saved login for ${name}: enter CLIENT_USERNAME and CLIENT_PASSWORD" }
          env.FW_NEW_LOGIN = pass ? 'yes' : ''

          def rules = (JOB_ACTION == 'open' ? params.RULES_ADD : params.RULES_REMOVE) ?: ''
          if (!rules.readLines().any { it.trim() && !it.trim().startsWith('#') }) {
            error "Enter at least one rule in ${JOB_ACTION == 'open' ? 'RULES_ADD' : 'RULES_REMOVE'}"
          }
          env.FW_RULES = rules
          currentBuild.description = "${name} (${ip}) ${JOB_ACTION == 'open' ? 'open' : 'remove'} ports, by ${env.FW_REQUESTER}"
        }
        deleteDir()
        script { gitAuth("clone -q ${REPO_URL} repo") }
        writeFile file: 'rules.txt', text: env.FW_RULES
        dir('repo') {
          script {
            env.FW_BASE_SHA = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
            // Open: OS and port from the form. Remove: the client's current values from the inventory.
            def what = JOB_ACTION == 'remove' ? '--existing --remove ../rules.txt' :
                       '--os "$OS_TYPE" ' + (JOB_FAMILY == 'linux' ? '--ssh-port "$SSH_PORT"' : '--rdp-port "$RDP_PORT"') + ' --add ../rules.txt'
            def rc = sh(returnStatus: true, script: '''
              git config user.name pi-jenkins && git config user.email jenkins@pi-dc.local
              python3 scripts/form_change.py --family ''' + JOB_FAMILY + ''' --name "$FW_NAME" --ip "$FW_IP" \
                --cred-id "$FW_CRED_ID" --requested-by "$FW_REQUESTER" ''' + what)
            if (rc == 10) {
              error 'Nothing to change: the client and its rules are already like this in main.'
            } else if (rc != 0) {
              error 'The request is not valid (see the ERROR line above). Nothing was changed.'
            }
            sh '''
              git --no-pager diff --color=always
              git add -A inventory/hosts.yml host_vars/
              printf 'Firewall change for %s (%s) via Jenkins form\\n\\nRequested-by: %s\\nFw-Form-Build: %s\\n' \
                "$FW_NAME" "$FW_IP" "$FW_REQUESTER" "$BUILD_URL" | git commit -q -F -
              git log --oneline -1
            '''
            def hv = sh(returnStdout: true, script: '''
              ansible-inventory -i inventory/hosts.yml --host "$FW_NAME" |
                python3 -c 'import sys,json; h=json.load(sys.stdin); print(h["os_baseline"], h.get("fw_ssh_port", 22))'
            ''').trim().tokenize(' ')
            env.FW_OS = hv[0]
            env.FW_SSH_PORT = hv[1]
          }
          sh 'ansible-galaxy collection install -r collections/requirements.yml -p ./collections'
          sh 'yamllint . && ansible-lint playbooks roles && bash scripts/no_package_installs.sh && python3 scripts/form_jobs.py --check'
          sh '''
            BASE=$(git describe --tags --abbrev=0 --match 'deployed-*' HEAD 2>/dev/null || true)
            echo "Last deployed: ${BASE:-none (Day 1)}"
            bash scripts/plan.sh "$BASE"
            # The client is always applied, so new clients get their protected rules and policy
            # even without rule changes.
            [ -f "plans/$FW_NAME.yml" ] || printf 'fw_add: []\\nfw_remove: []\\n' > "plans/$FW_NAME.yml"
          '''
          archiveArtifacts artifacts: 'plans/**', allowEmptyArchive: true
        }
      }
    }

    stage('Stage 2 - Login') {
      agent { label 'ansible' }
      steps {
        sh '''
          [ -n "$FW_IS_LINUX" ] || exit 0
          KH="$HOME/.ssh/known_hosts"; mkdir -p "$HOME/.ssh"; touch "$KH"
          if [ "$FW_SSH_PORT" = 22 ]; then HN="$FW_IP"; else HN="[$FW_IP]:$FW_SSH_PORT"; fi
          if ssh-keygen -F "$HN" -f "$KH" >/dev/null; then
            echo "Host key for $HN already known:"
          else
            ssh-keyscan -T 10 -p "$FW_SSH_PORT" "$FW_IP" 2>/dev/null > keyscan.txt
            [ -s keyscan.txt ] || { echo "ERROR: no SSH server answered on $FW_IP:$FW_SSH_PORT"; exit 1; }
            cat keyscan.txt >> "$KH"
            echo "First connection to $HN: recorded its host keys. Check these fingerprints if in doubt:"
          fi
          ssh-keygen -F "$HN" -f "$KH" | grep -v '^#' | ssh-keygen -lf -
        '''
        dir('repo') {
          script {
            // New details are tested under a pending credential and replace the saved login only if they work.
            env.FW_LOGIN_ID = env.FW_CRED_ID
            if (env.FW_NEW_LOGIN) {
              env.FW_LOGIN_ID = "${env.FW_CRED_ID}-pending-${JOB_SLUG}-${env.BUILD_NUMBER}"
              saveLogin(env.FW_LOGIN_ID, params.CLIENT_USERNAME, plainText(params.CLIENT_PASSWORD), "Being tested by ${env.BUILD_URL}")
            }
            try {
              withClientCreds {
                // A fresh SSH connection: a reused one (ControlPersist) would pass without checking the password.
                sh 'ANSIBLE_SSH_ARGS="-C -o ControlMaster=no -o ControlPath=none" bash scripts/run-playbook.sh playbooks/login_check.yml "$FW_NAME" --private-key "$SSH_KEY"'
              }
            } catch (e) {
              error "Login to ${env.FW_NAME} (${env.FW_IP}) failed with ${env.FW_NEW_LOGIN ? 'the details entered' : 'the saved login'} (see above). Nothing was changed."
            } finally {
              if (env.FW_NEW_LOGIN) { deleteLogin(env.FW_LOGIN_ID) }
            }
            if (env.FW_NEW_LOGIN) {
              def how = saveLogin(env.FW_CRED_ID, params.CLIENT_USERNAME, plainText(params.CLIENT_PASSWORD),
                "Login for client ${env.FW_NAME} (${env.FW_IP}), set by ${env.FW_REQUESTER} in build ${env.BUILD_NUMBER}")
              echo "Login works: ${how} Jenkins credential '${env.FW_CRED_ID}' (user ${params.CLIENT_USERNAME})."
            }
            env.FW_LOGIN_ID = env.FW_CRED_ID
          }
          withClientCreds {
            sh 'bash scripts/run-playbook.sh playbooks/firewall_service.yml "$FW_NAME" --private-key "$SSH_KEY" -e fw_service_mode=check'
          }
        }
      }
    }

    stage('Stage 3 - Push and review') {
      agent { label 'ansible' }
      steps {
        dir('repo') {
          withClientCreds {
            sh 'bash scripts/run-playbook.sh playbooks/firewall.yml "$FW_NAME" --private-key "$SSH_KEY" --check --diff'
          }
          script {
            env.FW_BRANCH = "form/${JOB_SLUG}-${env.FW_NAME}-${env.BUILD_NUMBER}"
            env.FW_TITLE = JOB_ACTION == 'open' ? "Open firewall ports on ${env.FW_NAME} (${env.FW_IP})" : "Remove firewall ports from ${env.FW_NAME} (${env.FW_IP})"
            gitAuth('push -q origin "HEAD:refs/heads/$FW_BRANCH"')
            def plan = readFile("plans/${env.FW_NAME}.yml").trim()
            writeFile file: '../pr_body.md', text: """${env.FW_TITLE}, ${env.FW_OS}: requested by **${env.FW_REQUESTER}** in [${env.JOB_NAME} #${env.BUILD_NUMBER}](${env.BUILD_URL}).

Login, firewall status and dry run passed in that build. **Approve this PR to apply it**: Jenkins merges it once the PR build is green and every requested reviewer (${env.FW_REVIEWERS}) approved, then applies the rules to ${env.FW_NAME}. If applying fails, Jenkins reverts the merge and applies the old rules again.

Plan for ${env.FW_NAME}:
```yaml
${plan}
```
"""
            withGitHub(REPO) {
              env.FW_PR = sh(returnStdout: true, script: '''
                python3 scripts/form_pr.py open --branch "$FW_BRANCH" --body-file ../pr_body.md \
                  --title "$FW_TITLE ($JOB_NAME #$BUILD_NUMBER)" --reviewers "$FW_REVIEWERS"
              ''').trim()
            }
            echo "Pull request: https://github.com/${REPO}/pull/${env.FW_PR} (review requested from ${env.FW_REVIEWERS})"
          }
        }
      }
    }

    // Waits outside the agent: its only executor must stay free for the PR build this waits for.
    stage('Stage 4 - Approve and merge') {
      steps {
        script {
          echo "Waiting up to ${REVIEW_HOURS} h for https://github.com/${REPO}/pull/${env.FW_PR}: Jenkins PR build SUCCESS and approval by ${env.FW_REVIEWERS}."
          def last = ''
          timeout(time: REVIEW_HOURS, unit: 'HOURS') {
            while (!env.FW_MERGE_SHA) {
              def rc, out
              node('ansible') {
                dir('repo') {
                  withGitHub(REPO) {
                    rc = sh(returnStatus: true, script: '''
                      python3 scripts/form_pr.py check --pr "$FW_PR" --require "$FW_REVIEWERS" --merge-sha-file ../merge_sha.txt \
                        --message "Merged by Jenkins $JOB_NAME after approval.

Fw-Form-Build: $BUILD_URL" > ../check.txt 2>&1
                    ''')
                  }
                  out = readFile('../check.txt').trim()
                  if (rc == 0) { env.FW_MERGE_SHA = readFile('../merge_sha.txt').trim() }
                }
              }
              if (out != last) { echo out; last = out }
              if (rc == 20) { error "Not merged: ${out}. Nothing was applied." }
              if (rc != 0 && rc != 10) { error "Checking the pull request failed: ${out}" }
              if (!env.FW_MERGE_SHA) { sleep(time: 60, unit: 'SECONDS') }
            }
          }
          echo "Merged to main as ${env.FW_MERGE_SHA.take(7)}."
        }
      }
    }

    stage('Stage 5 - Apply') {
      agent { label 'ansible' }
      steps {
        script {
          env.FW_TAG = "${JOB_SLUG}-${env.BUILD_NUMBER}"
          try {
            dir('repo') {
              gitAuth('fetch -q origin main')
              sh '''
                git checkout -q "$FW_MERGE_SHA"
                BASE=$(git describe --tags --abbrev=0 --match 'deployed-*' HEAD 2>/dev/null || true)
                echo "Last deployed: ${BASE:-none (Day 1)}"
                bash scripts/plan.sh "$BASE"
                [ -f "plans/$FW_NAME.yml" ] || printf 'fw_add: []\\nfw_remove: []\\n' > "plans/$FW_NAME.yml"
              '''
              archiveArtifacts artifacts: 'plans/**', allowEmptyArchive: true
              def others = fileExists('plans/hosts.txt') ? readFile('plans/hosts.txt').trim().tokenize('\n') - [env.FW_NAME] : []
              env.FW_OTHERS = others.join(',')
              if (others) {
                echo "WARNING: other clients also have changes in git that are not deployed yet: ${env.FW_OTHERS}. " +
                     'This build changes only ' + env.FW_NAME + '; deploy the others through the os-firewall main build.'
              }
              withClientCreds {
                sh 'ANSIBLE_LOG_PATH=apply.log bash scripts/run-playbook.sh playbooks/firewall_service.yml "$FW_NAME" --private-key "$SSH_KEY" -e fw_service_mode=ensure'
                sh 'ANSIBLE_LOG_PATH=apply.log bash scripts/run-playbook.sh playbooks/firewall.yml "$FW_NAME" --private-key "$SSH_KEY"'
              }
              if (env.FW_OTHERS) {
                echo "Not tagging: ${env.FW_OTHERS} still have undeployed changes."
              } else {
                sh 'git -c user.name=pi-jenkins -c user.email=jenkins@pi-dc.local tag -a "deployed-$FW_TAG" -m "Applied to $FW_NAME (requested by $FW_REQUESTER, PR #$FW_PR) in $BUILD_URL"'
                gitAuth('push -q origin "deployed-$FW_TAG"')
                echo "Tagged deployed-${env.FW_TAG}."
              }
            }
          } catch (e) {
            env.FW_APPLY_FAILED = e.toString()
            unstable "Applying failed: ${e}. Stage 6 rolls back."
          }
        }
      }
    }

    stage('Stage 6 - Result') {
      agent { label 'ansible' }
      steps {
        dir('repo') {
          script {
            if (!env.FW_APPLY_FAILED) {
              writeFile file: '../result.md', text: "Applied to ${env.FW_NAME} by [Jenkins build #${env.BUILD_NUMBER}](${env.BUILD_URL}): SUCCESS."
              withGitHub(REPO) {
                sh 'python3 scripts/form_pr.py comment --pr "$FW_PR" --body-file ../result.md && python3 scripts/form_pr.py delete-branch --pr "$FW_PR"'
              }
              echo "SUCCESS: ${env.FW_NAME} (${env.FW_IP}) has the new firewall rules. PR #${env.FW_PR} merged as ${env.FW_MERGE_SHA.take(7)}."
              return
            }
            echo "FAILED in Stage 5 (${env.FW_APPLY_FAILED}). Rolling back: revert PR #${env.FW_PR} on main, then apply the old rules."
            def problems = []
            // 1. Old code back on main. The trailer keeps the os-firewall main build from applying it again.
            gitAuth('fetch -q origin main')
            def rc = sh(returnStatus: true, script: '''
              git checkout -q -B rollback origin/main
              git -c user.name=pi-jenkins -c user.email=jenkins@pi-dc.local revert --no-edit -m 1 "$FW_MERGE_SHA" &&
              git -c user.name=pi-jenkins -c user.email=jenkins@pi-dc.local commit -q --amend -m "Revert PR #$FW_PR: applying it to $FW_NAME failed

Rolled back by Jenkins $JOB_NAME.

Fw-Form-Build: $BUILD_URL"
            ''')
            if (rc == 0) {
              try { gitAuth('push -q origin HEAD:main'); echo 'main: PR reverted.' }
              catch (e) { problems << "pushing the revert to main failed (${e.message})" }
            } else {
              sh 'git revert --abort 2>/dev/null || true'
              problems << 'reverting the merge on main failed (main changed since; revert it in GitHub)'
            }
            // 2. Old rules back on the client. Uses the merged inventory: a new client is still listed there.
            sh 'git checkout -q -f "$FW_MERGE_SHA"'
            rc = sh(returnStatus: true, script: 'bash scripts/rollback_plan.sh "$FW_MERGE_SHA" "$FW_MERGE_SHA^1" "$FW_NAME"')
            if (rc != 0) {
              problems << 'working out the old rules failed'
            } else if (fileExists('plans/hosts.txt')) {
              archiveArtifacts artifacts: 'plans/**', allowEmptyArchive: true
              withClientCreds {
                rc = sh(returnStatus: true, script: 'ANSIBLE_LOG_PATH=apply.log bash scripts/run-playbook.sh playbooks/firewall.yml "$FW_NAME" --private-key "$SSH_KEY"')
              }
              if (rc != 0) { problems << "applying the old rules to ${env.FW_NAME} failed (see above)" }
            }
            def summary = problems ? "Rollback INCOMPLETE: ${problems.join('; ')}. Check ${env.FW_NAME} by hand." :
                                     "Rolled back: PR reverted on main and the old rules applied to ${env.FW_NAME} (the firewall stays enabled)."
            writeFile file: '../result.md', text: "Applying to ${env.FW_NAME} FAILED in [Jenkins build #${env.BUILD_NUMBER}](${env.BUILD_URL}): ${env.FW_APPLY_FAILED}\n\n${summary}"
            withGitHub(REPO) {
              sh 'python3 scripts/form_pr.py comment --pr "$FW_PR" --body-file ../result.md; python3 scripts/form_pr.py delete-branch --pr "$FW_PR"'
            }
            error "FAILED: ${env.FW_APPLY_FAILED}. ${summary}"
          }
        }
      }
    }
  }
  post {
    unsuccessful {
      script {
        // Stopped before the merge: close the PR so nothing half-done stays open.
        if (env.FW_PR && !env.FW_MERGE_SHA) {
          node('ansible') {
            dir('repo') {
              writeFile file: '../closed.md', text: "Closed by [Jenkins build #${env.BUILD_NUMBER}](${env.BUILD_URL}) (${currentBuild.currentResult}): it was not merged, so nothing was applied. Run the form again to retry."
              withGitHub(REPO) { sh 'python3 scripts/form_pr.py close --pr "$FW_PR" --body-file ../closed.md || true' }
            }
          }
        }
      }
    }
    always {
      script {
        node('ansible') {
          archiveArtifacts artifacts: 'repo/apply.log', allowEmptyArchive: true
          deleteDir()
        }
      }
    }
  }
}
