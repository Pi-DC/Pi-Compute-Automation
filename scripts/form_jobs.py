#!/usr/bin/env python3
"""The four Jenkins firewall form jobs, generated from jenkins/firewall-form-template.groovy.

  form_jobs.py                     write jenkins/jobs/<job>.groovy for every job
  form_jobs.py --check             fail if a jenkins/jobs/<job>.groovy is not up to date (Lint runs this)
  form_jobs.py --config-xml <job>  print the job's Jenkins config.xml (create-job / update-job input)

Each job only adds or only removes rules, for Linux or for Windows clients. They share the pipeline, so a
fix in the template reaches all four.
"""
import argparse
import os
import sys
from xml.sax.saxutils import escape

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TEMPLATE = os.path.join(ROOT, "jenkins", "firewall-form-template.groovy")
OUT_DIR = os.path.join(ROOT, "jenkins", "jobs")

OS_CHOICES = {"linux": ["Ubuntu-24", "Ubuntu-22", "Ubuntu-20", "RedHat-9", "RedHat-8", "RedHat-7", "Rocky-9", "Rocky-8", "AlmaLinux-9", "AlmaLinux-8", "OracleLinux-9", "OracleLinux-8", "OracleLinux-7", "CentOS-9", "CentOS-8", "CentOS-7"],
              "windows": ["Windows-2022", "Windows-2019"]}

JOBS = {
    "Pi-Linux-Systems-OSFW-Add": ("linux", "open", "linux-open", "Open firewall ports (add rules) on a Linux client. Adds a new client if it is not known yet."),
    "Pi-Linux-Systems-OSFW-Remove": ("linux", "remove", "linux-remove", "Remove firewall rules from a known Linux client."),
    "Pi-Windows-Systems-OSFW-Add": ("windows", "open", "windows-open", "Open firewall ports (add rules) on a Windows client. Adds a new client if it is not known yet."),
    "Pi-Windows-Systems-OSFW-Remove": ("windows", "remove", "windows-remove", "Remove firewall rules from a known Windows client."),
}

# No rule is added by default: the client's rules must let the Jenkins agent reach its connection port.
ACCESS = {"linux": "its SSH port", "windows": "WinRM port 5986"}

RULE_FORMAT = ("One rule per line: <code>SOURCE  DESTINATION  PORTS  [tcp|udp]  [comment]</code><br>"
               "SOURCE / DESTINATION = <code>any</code>, an IP or a CIDR. PORTS = <code>443</code>, <code>8000-8010</code> "
               "or <code>80,443</code>. Protocol defaults to tcp.")


def params(family, action):
    """[(type, name, default, description, choices)] in form order."""
    known = action == "remove"
    p = [
        ("string", "CLIENT_IP", "", "IP address of the client" + (" (as in the inventory)" if known else ", e.g. 172.20.119.111"), None),
        ("string", "CLIENT_NAME", "", ("Name of the client as in the inventory. " if known else
                                       "Optional short name (lowercase, digits, -). Use the same name every time for the same client. ")
         + "Empty = client-&lt;IP with dashes&gt;.", None),
    ]
    if action == "open":
        p.append(("choice", "OS_TYPE", None, "Operating system and major version of the client (must match the inventory for a known client). "
         + ("CentOS-8 = CentOS Linux 8 or Stream 8, CentOS-9 = CentOS Stream 9." if family == "linux" else ""), OS_CHOICES[family]))
    who = "SSH user with sudo" if family == "linux" else "local or DOMAIN\\user admin for WinRM"
    p += [
        ("string", "CLIENT_USERNAME", "", f"Required: login user ({who}).", None),
        ("password", "CLIENT_PASSWORD", "", "Required: password for that user. Used only while this build runs: "
         "never in git, and deleted from Jenkins when the build ends (it is not kept with the build either).", None),
    ]
    if action == "open" and family == "linux":
        p.append(("string", "SSH_PORT", "", "Port the SSH server listens on; Ansible connects here. "
                  "Empty = keep the client's current port (22 for a new client).", None))
    if action == "open":
        p.append(("text", "RULES_ADD", "", "Firewall rules to OPEN. " + RULE_FORMAT
                  + "<br>Example: <code>172.20.120.0/24 any 80,443 tcp Web from app subnet</code>"
                  + f"<br>No rule is added by default. The client's rules must allow the Jenkins agent 172.20.119.105 to reach {ACCESS[family]} "
                  + "(a new client needs that rule here, e.g. <code>172.20.119.105 any "
                  + ("22" if family == "linux" else "5986") + " tcp Jenkins</code>), or the build stops at Plan.", None))
    else:
        p.append(("text", "RULES_REMOVE", "", "Firewall rules to REMOVE (each must exist on this client). " + RULE_FORMAT
                  + "<br>Example: <code>172.20.120.0/24 any 443 tcp</code>"
                  + f"<br>Removing the last rule that lets the Jenkins agent 172.20.119.105 reach {ACCESS[family]} is refused at Plan.", None))
    p.append(("string", "REVIEWERS", "", "Optional: more GitHub users to review the pull request, comma-separated. "
              "Pi-KiranRaja is always asked. Every reviewer must approve before the merge.", None))
    return p


def q(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def groovy_params(family, action):
    out = []
    for kind, name, default, desc, choices in params(family, action):
        if kind == "choice":
            out.append(f"    choice(name: {q(name)}, choices: [{', '.join(q(c) for c in choices)}], description: {q(desc)})")
        elif kind == "password":
            out.append(f"    password(name: {q(name)}, defaultValue: '', description: {q(desc)})")
        elif kind == "text":
            out.append(f"    text(name: {q(name)}, defaultValue: {q(default)}, description: {q(desc)})")
        else:
            out.append(f"    string(name: {q(name)}, defaultValue: {q(default)}, trim: true, description: {q(desc)})")
    return "\n".join(out)


def script(job):
    family, action, slug, desc = JOBS[job]
    with open(TEMPLATE) as f:
        s = f.read()
    for k, v in {"@@HEADER@@": f'Jenkins job "{job}": {desc}', "@@FAMILY@@": family, "@@ACTION@@": action,
                 "@@SLUG@@": slug, "@@PARAMETERS@@": groovy_params(family, action)}.items():
        s = s.replace(k, v)
    return s


def config_xml(job):
    family, action, _, desc = JOBS[job]
    defs = []
    for kind, name, default, pdesc, choices in params(family, action):
        cls = {"string": "StringParameterDefinition", "choice": "ChoiceParameterDefinition",
               "password": "PasswordParameterDefinition", "text": "TextParameterDefinition"}[kind]
        body = f"<name>{name}</name><description>{escape(pdesc)}</description>"
        if kind == "choice":
            body += "<choices class=\"java.util.Arrays$ArrayList\"><a class=\"string-array\">" + "".join(
                f"<string>{escape(c)}</string>" for c in choices) + "</a></choices>"
        elif kind == "string":
            body += f"<defaultValue>{escape(default)}</defaultValue><trim>true</trim>"
        elif kind == "text":
            body += f"<defaultValue>{escape(default)}</defaultValue><trim>false</trim>"
        defs.append(f"<hudson.model.{cls}>{body}</hudson.model.{cls}>")
    return f"""<?xml version='1.1' encoding='UTF-8'?>
<flow-definition>
  <description>{escape(desc + " Pipeline: jenkins/jobs/" + job + ".groovy (generated from jenkins/firewall-form-template.groovy).")}</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <hudson.model.ParametersDefinitionProperty><parameterDefinitions>{''.join(defs)}</parameterDefinitions></hudson.model.ParametersDefinitionProperty>
    <jenkins.model.BuildDiscarderProperty><strategy class="hudson.tasks.LogRotator"><daysToKeep>365</daysToKeep><numToKeep>-1</numToKeep><artifactDaysToKeep>-1</artifactDaysToKeep><artifactNumToKeep>-1</artifactNumToKeep></strategy></jenkins.model.BuildDiscarderProperty>
    <org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty><abortPrevious>false</abortPrevious></org.jenkinsci.plugins.workflow.job.properties.DisableConcurrentBuildsJobProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">
    <script>{escape(script(job))}</script>
    <sandbox>false</sandbox>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--config-xml", choices=sorted(JOBS))
    a = ap.parse_args()
    if a.config_xml:
        sys.stdout.write(config_xml(a.config_xml))
        return
    stale = []
    os.makedirs(OUT_DIR, exist_ok=True)
    for job in JOBS:
        path = os.path.join(OUT_DIR, f"{job}.groovy")
        want = script(job)
        try:
            with open(path) as f:
                have = f.read()
        except FileNotFoundError:
            have = None
        if have == want:
            continue
        if a.check:
            stale.append(path)
        else:
            with open(path, "w") as f:
                f.write(want)
            print(f"wrote {os.path.relpath(path, ROOT)}")
    if stale:
        sys.exit("ERROR: out of date (run python3 scripts/form_jobs.py and commit): " + ", ".join(os.path.relpath(p, ROOT) for p in stale))
    if a.check:
        print("Form job scripts are up to date.")


if __name__ == "__main__":
    main()
