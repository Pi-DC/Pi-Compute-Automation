// Jenkins job "pr-auto-merge" (Pipeline from SCM: this file on main).
// Every 2 minutes: merge each open PR whose Jenkins PR build is SUCCESS and that an approver
// (FW_APPROVERS in the Jenkinsfile) approved on its final commit. Rules: scripts/auto_merge.py.
// Merging applies nothing: the os-firewall main build still waits for the Apply click.
pipeline {
  agent { label 'ansible' }
  triggers { cron('H/2 * * * *') }
  options {
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '300'))
    timeout(time: 10, unit: 'MINUTES')
  }
  stages {
    stage('Merge ready PRs') {
      steps {
        withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
          withEnv(['GITHUB_REPOSITORY=Pi-DC/os-firewall-automation']) {
            sh 'python3 scripts/auto_merge.py'
          }
        }
      }
    }
  }
}
