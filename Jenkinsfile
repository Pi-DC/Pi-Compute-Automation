// OS firewall automation
//   PR builds  : lint -> plan -> firewall status -> dry run (--check --diff) on the changed hosts.
//                Nothing is changed.
//   main builds: lint -> plan -> firewall status -> approval check (merged PR approved by admin)
//                -> admin clicks Apply -> enable + start the firewall where it is off
//                -> Ansible applies only the changed rules on only the changed hosts -> tag deployed-N

// ---- CHANGE THESE THREE VALUES ----------------------------------------------------------
def REPO             = 'Pi-DC/Pi-Compute-Automation'
def FW_APPROVERS     = 'Pi-KiranRaja'                      // GitHub user(s) who may approve PRs, comma-separated
def JENKINS_APPROVER = 'Pi-Compute'                        // Jenkins user ID(s) who may click Apply
// ------------------------------------------------------------------------------------------

// Shared credentials, plus the Jenkins credential of every host in FW_HOSTS that names one in
// inventory/hosts.yml (fw_cred_id, set by the firewall form jobs). The inventory reads them
// from FWCRED_<HOST>_USER / FWCRED_<HOST>_PASS, so no password is ever stored in git. A form job's
// client login exists only while that job runs (its PR build runs then), so change form-managed
// clients through the form jobs: no password is kept in Jenkins between builds.
def withFwCreds(Closure body) {
  def creds = [
    usernamePassword(credentialsId: 'ansible-win-cred', usernameVariable: 'WIN_USER', passwordVariable: 'WIN_PASS')
  ]
  for (h in (env.FW_HOSTS ?: '').tokenize(',')) {
    def id = sh(returnStdout: true, script: """ansible-inventory -i inventory/hosts.yml --host '${h}' | python3 -c 'import sys,json; print(json.load(sys.stdin).get("fw_cred_id", ""))'""").trim()
    if (id) {
      def v = 'FWCRED_' + h.toUpperCase().replaceAll('[^A-Z0-9]', '_')
      creds << usernamePassword(credentialsId: id, usernameVariable: "${v}_USER", passwordVariable: "${v}_PASS")
    }
  }
  withCredentials(creds) { body() }
}

pipeline {
  agent { label 'ansible' }
  options {
    timestamps()
    ansiColor('xterm')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(daysToKeepStr: '365'))
  }
  environment {
    ANSIBLE_FORCE_COLOR = 'true'
  }
  stages {
    stage('Setup') {
      steps {
        sh 'ansible-galaxy collection install -r collections/requirements.yml -p ./collections'
      }
    }

    stage('Lint') {
      steps {
        sh 'yamllint . && ansible-lint playbooks roles && bash scripts/no_package_installs.sh && python3 scripts/form_jobs.py --check'
      }
    }

    stage('Plan') {
      steps {
        sh '''
          BASE=$(git describe --tags --abbrev=0 --match 'deployed-*' HEAD 2>/dev/null || true)
          echo "Last deployed: ${BASE:-none (Day 1)}"
          bash scripts/plan.sh "$BASE"
        '''
        archiveArtifacts artifacts: 'plans/**', allowEmptyArchive: true
        script {
          env.FW_HOSTS = fileExists('plans/hosts.txt') ? readFile('plans/hosts.txt').trim().replace('\n', ',') : ''
          // Changes from a firewall form job (its merge or revert commit, or a form/* PR merged by
          // hand: trailer on the merged commit HEAD^2) are approved and applied by that job.
          def formBuild = sh(returnStdout: true, script: "{ git log -1 --format=%B HEAD; git log -1 --format=%B HEAD^2 2>/dev/null || true; } | sed -n 's/^Fw-Form-Build: //p' | head -1").trim()
          if (env.BRANCH_NAME == 'main' && formBuild) {
            echo "Change made by a firewall form job (${formBuild}); it was approved and applied there."
            env.FW_HOSTS = ''
          }
          echo(env.FW_HOSTS ? "Hosts to change: ${env.FW_HOSTS}" : 'No firewall changes in this build.')
        }
      }
    }

    // Is the firewall enabled and running on every host of this change? Reports only.
    stage('Firewall status') {
      when { expression { env.FW_HOSTS } }
      steps {
        withFwCreds {
          sh 'bash scripts/run-playbook.sh playbooks/firewall_service.yml "$FW_HOSTS" -e fw_service_mode=check'
        }
      }
    }

    stage('Dry run') {
      when { allOf { changeRequest(); expression { env.FW_HOSTS } } }
      steps {
        withFwCreds {
          sh 'bash scripts/run-playbook.sh playbooks/firewall.yml "$FW_HOSTS" --check --diff'
        }
      }
    }

    stage('Approval check') {
      when { allOf { branch 'main'; expression { env.FW_HOSTS } } }
      steps {
        withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
          withEnv(["GITHUB_REPOSITORY=${REPO}", "FW_APPROVERS=${FW_APPROVERS}", "COMMIT_SHA=${env.GIT_COMMIT}"]) {
            sh 'python3 scripts/approval_check.py'
          }
        }
      }
    }

    stage('Approve apply') {
      when { allOf { branch 'main'; expression { env.FW_HOSTS } } }
      steps {
        timeout(time: 24, unit: 'HOURS') {
          script {
            env.APPROVER = input(
              message: "Apply firewall changes to: ${env.FW_HOSTS} ? (see plans/ in this build's artifacts)",
              ok: 'Apply',
              submitter: JENKINS_APPROVER,
              submitterParameter: 'APPROVER')
          }
        }
      }
    }

    // Firewall off or stopped on a host: add the management rules, enable it at boot, start it.
    // Fails the build (before any rule changes) if it cannot.
    stage('Enable firewall') {
      when { allOf { branch 'main'; expression { env.FW_HOSTS } } }
      steps {
        withFwCreds {
          sh 'ANSIBLE_LOG_PATH=apply.log bash scripts/run-playbook.sh playbooks/firewall_service.yml "$FW_HOSTS" -e fw_service_mode=ensure'
        }
      }
    }

    stage('Update firewall rules') {
      when { allOf { branch 'main'; expression { env.FW_HOSTS } } }
      steps {
        withFwCreds {
          sh 'ANSIBLE_LOG_PATH=apply.log bash scripts/run-playbook.sh playbooks/firewall.yml "$FW_HOSTS"'
        }
        withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
          withEnv(["GITHUB_REPOSITORY=${REPO}"]) {
            sh '''
              git -c user.name=pi-jenkins -c user.email=jenkins@pi-dc.local tag -a "deployed-$BUILD_NUMBER" \
                  -m "Applied to $FW_HOSTS, approved by $APPROVER" "$GIT_COMMIT"
              git push "https://x-access-token:$GH_TOKEN@github.com/$GITHUB_REPOSITORY.git" "deployed-$BUILD_NUMBER"
            '''
          }
        }
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'apply.log', allowEmptyArchive: true
    }
    success {
      script {
        // A green pull request (not form/*: its form job merges it): one Pi-PR-Auto-Merge run for it, which
        // merges right after the approval. No schedule.
        if (env.CHANGE_ID && !(env.CHANGE_BRANCH ?: '').startsWith('form/')) {
          build job: '/Pi-PR-Auto-Merge', wait: false, parameters: [string(name: 'PR_NUMBER', value: env.CHANGE_ID)]
          echo "Started Pi-PR-Auto-Merge for PR #${env.CHANGE_ID}: it merges once the PR is approved."
        }
      }
    }
  }
}
