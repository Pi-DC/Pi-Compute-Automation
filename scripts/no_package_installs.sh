#!/usr/bin/env bash
# Policy: nothing is ever installed on a client. Fails if a playbook or role uses a package module
# or runs a package manager. Ansible's own temporary module files (removed after each task) are not packages.
set -uo pipefail
mods='package|yum|dnf|dnf5|apt|apt_key|apt_repository|apt_rpm|yum_repository|rpm_key|pip|pipx|easy_install|gem|npm|snap|flatpak|zypper|pkgng|homebrew|win_package|win_feature|win_optional_feature|win_chocolatey|chocolatey|win_psmodule|win_updates|win_hotfix'
cmds='(yum|dnf|apt|apt-get|zypper|pip3?|snap|choco|winget)[[:space:]]+(install|update|upgrade|reinstall)|rpm[[:space:]]+-[a-zA-Z]*[iUF]|dpkg[[:space:]]+-i|Install-(Package|Module|WindowsFeature)|Add-WindowsCapability|Enable-WindowsOptionalFeature|msiexec'
hits=$(grep -rnE "^[[:space:]]*-?[[:space:]]*([a-z_]+\.[a-z_]+\.)?($mods):" playbooks roles; grep -rnE "$cmds" playbooks roles)
if [ -n "$hits" ]; then
  echo "ERROR: installing packages on clients is not allowed:"; echo "$hits"; exit 1
fi
echo "No package installs on clients."
