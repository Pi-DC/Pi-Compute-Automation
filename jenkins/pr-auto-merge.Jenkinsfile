// Jenkins job "Pi-PR-Auto-Merge" (Pipeline from SCM: this file on main). No schedule.
// Started by the Pi-Compute-Automation build of a pull request when that build succeeds (Jenkinsfile, post/success),
// one run per PR: waits for the approval and merges right after it. Rules (scripts/auto_merge.py, pr_status):
// Jenkins PR build SUCCESS on the final commit, approved there by an approver (FW_APPROVERS in the Jenkinsfile)
// who is not the author, no "changes requested", no conflict. Form PRs (form/*) are merged by their form job.
// Merging applies nothing: the Pi-Compute-Automation main build still waits for the Apply click.
// GitHub cannot call this Jenkins (private address), so the run asks GitHub: every 10 s for the first hour,
// then every minute (API limits). It holds no executor while it waits.
pipeline {
  agent none
  parameters {
    string(name: 'PR_NUMBER', defaultValue: '', trim: true, description: 'Pull request to merge once approved (set by the PR build)')
  }
  options {
    buildDiscarder(logRotator(numToKeepStr: '200'))
    timeout(time: 14, unit: 'DAYS')
  }
  stages {
    stage('Wait for approval and merge') {
      steps {
        script {
          if (!(params.PR_NUMBER ==~ /\d+/)) { error 'PR_NUMBER must be a pull request number' }
          currentBuild.description = "PR #${params.PR_NUMBER}"
          node('ansible') {
            checkout scm
            stash name: 'merge-scripts', includes: 'scripts/*.py,Jenkinsfile'
          }
          def rc = 10
          def out = ''
          def last = ''
          def polls = 0
          while (rc == 10) {
            node('ansible') {
              deleteDir()
              unstash 'merge-scripts'
              withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
                withEnv(['GITHUB_REPOSITORY=Pi-DC/Pi-Compute-Automation']) {
                  rc = sh(returnStatus: true, script: '''
                    python3 scripts/form_pr.py check --pr "$PR_NUMBER" --merge-sha-file merge_sha.txt \
                      --message "Merged by Jenkins Pi-PR-Auto-Merge after approval." > check.txt 2>&1
                  ''')
                }
              }
              out = readFile('check.txt').trim()
            }
            if (out != last) { echo out; last = out }
            if (rc == 10) {
              polls++
              sleep(time: polls < 360 ? 10 : 60, unit: 'SECONDS')
            }
          }
          if (rc == 0) {
            currentBuild.description = "PR #${params.PR_NUMBER} merged"
          } else if (rc == 20) {
            currentBuild.description = "PR #${params.PR_NUMBER} not merged"
            currentBuild.result = 'NOT_BUILT'
            echo "Not merged: ${out}"
          } else {
            error "Checking PR #${params.PR_NUMBER} failed: ${out}"
          }
        }
      }
    }
  }
}
