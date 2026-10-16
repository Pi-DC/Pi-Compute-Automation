// OS firewall automation
//   PR builds  : lint -> plan -> firewall status -> dry run (--check --diff) on the changed hosts.
//                Nothing is changed.
//   main builds: lint -> plan -> firewall status -> approval check (merged PR approved by admin)
//                -> admin clicks Apply -> enable + start the firewall where it is off
//                -> Ansible applies only the changed rules on only the changed hosts -> tag deployed-N

// ---- CHANGE THESE THREE VALUES ----------------------------------------------------------
def REPO             = 'Pi-DC/os-firewall-automation'
def FW_APPROVERS     = 'Pi-KiranRaja'                      // GitHub user(s) who may approve PRs, comma-separated
def JENKINS_APPROVER = 'Pi-Compute'                        // Jenkins user ID(s) who may click Apply
// ------------------------------------------------------------------------------------------

// Shared credentials, plus the Jenkins credential of every host in FW_HOSTS that names one in
// inventory/hosts.yml (fw_cred_id, set by the client-firewall form job). The inventory reads them
// from FWCRED_<HOST>_USER / FWCRED_<HOST>_PASS, so no password is ever stored in git.
def withFwCreds(Closure body) {
  def creds = [
    sshUserPrivateKey(credentialsId: 'ansible-ssh-key', keyFileVariable: 'SSH_KEY'),
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
        sh 'yamllint . && ansible-lint playbooks roles'
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
          // Commits pushed by the client-firewall form job were approved and applied by that job.
          def formBuild = sh(returnStdout: true, script: "git log -1 --format=%B | sed -n 's/^Fw-Form-Build: //p'").trim()
          if (env.BRANCH_NAME == 'main' && formBuild) {
            echo "Change made by the client-firewall form job (${formBuild}); it approved and applied it there."
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
          sh 'ansible-playbook playbooks/firewall_service.yml --private-key "$SSH_KEY" -l "$FW_HOSTS" -e fw_service_mode=check'
        }
      }
    }

    stage('Dry run') {
      when { allOf { changeRequest(); expression { env.FW_HOSTS } } }
      steps {
        withFwCreds {
          sh 'ansible-playbook playbooks/firewall.yml --private-key "$SSH_KEY" -l "$FW_HOSTS" --check --diff'
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
          sh 'ANSIBLE_LOG_PATH=apply.log ansible-playbook playbooks/firewall_service.yml --private-key "$SSH_KEY" -l "$FW_HOSTS" -e fw_service_mode=ensure'
        }
      }
    }

    stage('Update firewall rules') {
      when { allOf { branch 'main'; expression { env.FW_HOSTS } } }
      steps {
        withFwCreds {
          sh 'ANSIBLE_LOG_PATH=apply.log ansible-playbook playbooks/firewall.yml --private-key "$SSH_KEY" -l "$FW_HOSTS"'
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
  }
}
