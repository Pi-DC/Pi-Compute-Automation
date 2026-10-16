// Jenkins job "client-firewall-form": add or change a client and its firewall rules from a form.
//
//   Build with Parameters -> check the request and save the client's login as Jenkins credential
//   client-<name> -> update inventory/hosts.yml + host_vars/<name>.yml -> lint -> plan
//   -> firewall status -> dry run -> Pi-Compute clicks Apply -> enable + start the firewall if it is off
//   -> push the commit to main -> Ansible applies the rules on that client -> tag deployed-form-<build>.
//
// This script is the job's own (admin-approved, not sandboxed) pipeline: saving a credential needs
// the Jenkins API. Keep this file and the job in sync: jenkins/README.md says how.
import com.cloudbees.plugins.credentials.CredentialsProvider
import com.cloudbees.plugins.credentials.CredentialsScope
import com.cloudbees.plugins.credentials.SystemCredentialsProvider
import com.cloudbees.plugins.credentials.common.StandardUsernamePasswordCredentials
import com.cloudbees.plugins.credentials.domains.Domain
import com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl
import hudson.security.ACL
import jenkins.model.Jenkins

def REPO_URL         = 'https://github.com/Pi-DC/os-firewall-automation.git'
def JENKINS_APPROVER = 'Pi-Compute'   // Jenkins user ID(s) who may click Apply (same as the Jenkinsfile)

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
def plainText(value) {
  value instanceof hudson.util.Secret ? value.getPlainText() : (value ?: '').toString()
}

def gitAuth(String cmd) {
  withCredentials([usernamePassword(credentialsId: 'github-app-fw', usernameVariable: 'GH_APP', passwordVariable: 'GH_TOKEN')]) {
    sh 'set +x; git -c http.extraHeader="Authorization: Basic $(printf \'x-access-token:%s\' "$GH_TOKEN" | base64 -w0)" ' + cmd
  }
}

def withClientCreds(Closure body) {
  withCredentials([
    sshUserPrivateKey(credentialsId: 'ansible-ssh-key', keyFileVariable: 'SSH_KEY'),
    usernamePassword(credentialsId: 'ansible-win-cred', usernameVariable: 'WIN_USER', passwordVariable: 'WIN_PASS'),
    usernamePassword(credentialsId: env.FW_CRED_ID, usernameVariable: "${env.FW_CRED_ENV}_USER", passwordVariable: "${env.FW_CRED_ENV}_PASS")
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
  parameters {
    string(name: 'CLIENT_IP', trim: true, description: 'IP address of the client system, e.g. 172.20.119.111')
    string(name: 'CLIENT_NAME', trim: true, description: 'Optional short name (lowercase, digits, -). Empty = client-&lt;IP with dashes&gt;. Use the same name every time for the same client.')
    choice(name: 'OS_TYPE', choices: ['Ubuntu-24', 'Ubuntu-22', 'RedHat-9', 'Windows-2022', 'Windows-2019'], description: 'Operating system of the client')
    string(name: 'CLIENT_USERNAME', trim: true, description: 'Login user. Linux: SSH user with sudo. Windows: local or DOMAIN\\user admin for WinRM. Empty with empty password = keep the saved login.')
    password(name: 'CLIENT_PASSWORD', defaultValue: '', description: 'Password for that user. Saved only in Jenkins (credential client-&lt;name&gt;), never in git. Empty = keep the saved one.')
    string(name: 'SSH_PORT', defaultValue: '22', trim: true, description: 'Linux: port the SSH server listens on (Ansible connects here; always allowed from the management network). Ignored for Windows.')
    string(name: 'RDP_PORT', defaultValue: '3389', trim: true, description: 'Windows: RDP port allowed from the admin subnet. Ignored for Linux.')
    text(name: 'RULES_ADD', defaultValue: '', description: '''Firewall rules to ADD, one per line:<br>
<code>SOURCE  DESTINATION  PORTS  [tcp|udp]  [comment]</code><br>
SOURCE / DESTINATION = <code>any</code>, an IP or a CIDR. PORTS = <code>443</code>, <code>8000-8010</code> or <code>80,443</code>. Protocol defaults to tcp.<br>
Example: <code>172.20.120.0/24 any 80,443 tcp Web from app subnet</code>''')
    text(name: 'RULES_REMOVE', defaultValue: '', description: 'Firewall rules to REMOVE, same format (SOURCE DESTINATION PORTS [proto]). The rule must exist on this client.')
  }
  stages {
    stage('Check request') {
      steps {
        script {
          def ip = params.CLIENT_IP ?: ''
          if (!(ip ==~ /\d{1,3}(\.\d{1,3}){3}/)) { error "CLIENT_IP '${ip}' is not an IPv4 address" }
          def name = (params.CLIENT_NAME ?: "client-${ip.replace('.', '-')}").toLowerCase()
          if (!(name ==~ /[a-z0-9][a-z0-9-]{0,62}/)) { error "CLIENT_NAME '${name}': use lowercase letters, digits and '-'" }
          env.FW_NAME = name
          env.FW_IP = ip
          env.FW_IS_LINUX = params.OS_TYPE.startsWith('Windows') ? '' : 'yes'
          env.FW_CRED_ID = "client-${name}"
          env.FW_CRED_ENV = 'FWCRED_' + name.toUpperCase().replaceAll('[^A-Z0-9]', '_')
          def causes = currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause')
          env.FW_REQUESTER = causes ? causes[0].userId : 'unknown'

          def user = params.CLIENT_USERNAME ?: ''
          def pass = plainText(params.CLIENT_PASSWORD)
          if (pass) {
            if (!user) { error 'Enter CLIENT_USERNAME together with CLIENT_PASSWORD' }
            def how = saveLogin(env.FW_CRED_ID, user, pass, "Login for client ${name} (${ip}), set by ${env.FW_REQUESTER} in build ${env.BUILD_NUMBER}")
            echo "Login for ${name} ${how} in Jenkins credential '${env.FW_CRED_ID}' (user ${user})."
          } else if (user) {
            error 'CLIENT_USERNAME given without CLIENT_PASSWORD: enter both to change the saved login, or neither to keep it'
          } else if (!findLogin(env.FW_CRED_ID)) {
            error "No saved login for ${name}: enter CLIENT_USERNAME and CLIENT_PASSWORD"
          } else {
            echo "Using the saved login '${env.FW_CRED_ID}'."
          }
          currentBuild.description = "${name} (${ip}) ${params.OS_TYPE}, by ${env.FW_REQUESTER}"
        }
      }
    }

    stage('Update repo') {
      steps {
        deleteDir()
        script { gitAuth("clone -q ${REPO_URL} repo") }
        writeFile file: 'rules_add.txt', text: params.RULES_ADD ?: ''
        writeFile file: 'rules_remove.txt', text: params.RULES_REMOVE ?: ''
        dir('repo') {
          script {
            def rc = sh(returnStatus: true, script: '''
              git config user.name pi-jenkins && git config user.email jenkins@pi-dc.local
              python3 scripts/form_change.py --name "$FW_NAME" --ip "$FW_IP" --os "$OS_TYPE" \
                --ssh-port "$SSH_PORT" --rdp-port "$RDP_PORT" --cred-id "$FW_CRED_ID" \
                --add ../rules_add.txt --remove ../rules_remove.txt --requested-by "$FW_REQUESTER"
            ''')
            if (rc == 10) {
              env.FW_NOCHANGE = 'yes'
              echo 'Nothing to change: the client and its rules are already like this in git.'
            } else if (rc != 0) {
              error 'The request is not valid (see the ERROR line above). Nothing was changed.'
            } else {
              sh '''
                git --no-pager diff --color=always
                git add -A inventory/hosts.yml host_vars/
                printf 'Firewall change for %s (%s) via Jenkins form\\n\\nRequested-by: %s\\nFw-Form-Build: %s\\n' \
                  "$FW_NAME" "$FW_IP" "$FW_REQUESTER" "$BUILD_URL" | git commit -q -F -
                git log --oneline -1
              '''
            }
          }
        }
      }
    }

    stage('Lint') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          sh 'ansible-galaxy collection install -r collections/requirements.yml -p ./collections'
          sh 'yamllint . && ansible-lint playbooks roles'
        }
      }
    }

    stage('Plan') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          sh '''
            BASE=$(git describe --tags --abbrev=0 --match 'deployed-*' HEAD 2>/dev/null || true)
            echo "Last deployed: ${BASE:-none (Day 1)}"
            bash scripts/plan.sh "$BASE"
            # The client is always applied, so new clients get their protected rules and policy
            # even without rule changes.
            [ -f "plans/$FW_NAME.yml" ] || printf 'fw_add: []\\nfw_remove: []\\n' > "plans/$FW_NAME.yml"
          '''
          archiveArtifacts artifacts: 'plans/**', allowEmptyArchive: true
          script {
            def others = fileExists('plans/hosts.txt') ? readFile('plans/hosts.txt').trim().tokenize('\n') - [env.FW_NAME] : []
            env.FW_OTHERS = others.join(',')
            if (others) {
              echo "WARNING: other clients also have changes in git that are not deployed yet: ${env.FW_OTHERS}. " +
                   'This build changes only ' + env.FW_NAME + '; deploy the others through the os-firewall main build.'
            }
          }
        }
      }
    }

    stage('SSH host key') {
      when { expression { !env.FW_NOCHANGE && env.FW_IS_LINUX } }
      steps {
        sh '''
          KH="$HOME/.ssh/known_hosts"; mkdir -p "$HOME/.ssh"; touch "$KH"
          if [ "$SSH_PORT" = 22 ]; then HN="$FW_IP"; else HN="[$FW_IP]:$SSH_PORT"; fi
          if ssh-keygen -F "$HN" -f "$KH" >/dev/null; then
            echo "Host key for $HN already known:"
          else
            ssh-keyscan -T 10 -p "$SSH_PORT" "$FW_IP" 2>/dev/null > keyscan.txt
            [ -s keyscan.txt ] || { echo "ERROR: no SSH server answered on $FW_IP:$SSH_PORT"; exit 1; }
            cat keyscan.txt >> "$KH"
            echo "First connection to $HN: recorded its host keys. Check these fingerprints if in doubt:"
          fi
          ssh-keygen -F "$HN" -f "$KH" | grep -v '^#' | ssh-keygen -lf -
        '''
      }
    }

    // Is the client's firewall enabled and running? Reports only.
    stage('Firewall status') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          withClientCreds {
            sh 'ansible-playbook playbooks/firewall_service.yml --private-key "$SSH_KEY" -l "$FW_NAME" -e fw_service_mode=check'
          }
        }
      }
    }

    stage('Dry run') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          withClientCreds {
            sh 'ansible-playbook playbooks/firewall.yml --private-key "$SSH_KEY" -l "$FW_NAME" --check --diff'
          }
        }
      }
    }

    stage('Approve apply') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        timeout(time: 24, unit: 'HOURS') {
          script {
            env.APPROVER = input(
              message: "Apply firewall change to ${env.FW_NAME} (${env.FW_IP})? Check the Update repo diff, Plan and Dry run above.",
              ok: 'Apply',
              submitter: JENKINS_APPROVER,
              submitterParameter: 'APPROVER')
          }
        }
      }
    }

    // Firewall off or stopped: add the management rules, enable it at boot, start it.
    // Before the push, so a failure here leaves main unchanged.
    stage('Enable firewall') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          withClientCreds {
            sh 'ANSIBLE_LOG_PATH=apply.log ansible-playbook playbooks/firewall_service.yml --private-key "$SSH_KEY" -l "$FW_NAME" -e fw_service_mode=ensure'
          }
        }
      }
    }

    stage('Push to GitHub') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          script {
            try {
              gitAuth('push -q origin HEAD:main')
            } catch (e) {
              error "Push to main failed (${e.message}). Usually main changed on GitHub while this build waited. No rules were changed; run the form again."
            }
          }
        }
      }
    }

    stage('Update firewall rules') {
      when { expression { !env.FW_NOCHANGE } }
      steps {
        dir('repo') {
          withClientCreds {
            sh 'ANSIBLE_LOG_PATH=apply.log ansible-playbook playbooks/firewall.yml --private-key "$SSH_KEY" -l "$FW_NAME"'
          }
          script {
            if (env.FW_OTHERS) {
              echo "Not tagging: ${env.FW_OTHERS} still have undeployed changes."
            } else {
              sh 'git tag -a "deployed-form-$BUILD_NUMBER" -m "Applied by $APPROVER (requested by $FW_REQUESTER) in $BUILD_URL"'
              gitAuth('push -q origin "deployed-form-$BUILD_NUMBER"')
              echo "Tagged deployed-form-${env.BUILD_NUMBER}."
            }
          }
        }
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'repo/apply.log', allowEmptyArchive: true
      deleteDir()
    }
  }
}
