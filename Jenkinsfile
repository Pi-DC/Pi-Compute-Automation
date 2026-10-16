// OS firewall automation
//   PR builds  : lint -> plan -> dry run (--check --diff) on the changed hosts. Nothing is changed.
//   main builds: lint -> plan -> approval check (merged PR approved by admin) -> admin clicks Apply
//                -> Ansible applies only the changed rules on only the changed hosts -> tag deployed-N

// ---- CHANGE THESE THREE VALUES ----------------------------------------------------------
def REPO             = 'Pi-DC/os-firewall-automation'
def FW_APPROVERS     = 'CHANGE-ME-admin-github-username'   // GitHub user(s) who may approve PRs, comma-separated
def JENKINS_APPROVER = 'CHANGE-ME-admin-jenkins-userid'    // Jenkins user ID(s) who may click Apply
// ------------------------------------------------------------------------------------------

def withFwCreds(Closure body) {
  withCredentials([
    sshUserPrivateKey(credentialsId: 'ansible-ssh-key', keyFileVariable: 'SSH_KEY'),
    usernamePassword(credentialsId: 'ansible-win-cred', usernameVariable: 'WIN_USER', passwordVariable: 'WIN_PASS')
  ]) { body() }
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
          echo(env.FW_HOSTS ? "Hosts to change: ${env.FW_HOSTS}" : 'No firewall changes in this build.')
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

    stage('Apply') {
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
