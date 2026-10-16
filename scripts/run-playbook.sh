#!/usr/bin/env bash
# Run a playbook on the given hosts, each with the Ansible and Python that can manage it.
#   scripts/run-playbook.sh <playbook> <host,host,...> [ansible-playbook options...]
# Nothing is installed on a client, so Ansible must work with the Python its OS ships.
# ansible-core 2.21 (the ansible-playbook on PATH) needs Python 3.9+ on the client. Older systems (os_baseline
# in LEGACY below) run with ansible-core 2.16 from $FW_LEGACY_ANSIBLE and collections/requirements-el7.yml,
# using that system's own Python (it has the firewalld / ufw bindings):
#   EL7  (CentOS/RedHat/OracleLinux 7)            Python 2.7  /usr/bin/python
#   EL8  (CentOS/RedHat/Rocky/AlmaLinux/Oracle 8) Python 3.6  /usr/libexec/platform-python
#   Ubuntu 20.04                                  Python 3.8  /usr/bin/python3
# Current hosts run first, then each legacy Python group. A failure stops before the next group.
set -euo pipefail
PLAYBOOK=$1 HOSTS=$2
shift 2
declare -A LEGACY=(
  [CentOS-7]=/usr/bin/python [RedHat-7]=/usr/bin/python [OracleLinux-7]=/usr/bin/python
  [CentOS-8]=/usr/libexec/platform-python [RedHat-8]=/usr/libexec/platform-python
  [Rocky-8]=/usr/libexec/platform-python [AlmaLinux-8]=/usr/libexec/platform-python
  [OracleLinux-8]=/usr/libexec/platform-python
  [Ubuntu-20]=/usr/bin/python3
)
LEGACY_BIN=${FW_LEGACY_ANSIBLE:-/opt/ansible-el7/bin}

current=()
declare -A by_python=() os_of=()
for h in ${HOSTS//,/ }; do
  os=$(ansible-inventory -i inventory/hosts.yml --host "$h" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("os_baseline", ""))')
  py=${LEGACY[$os]:-}
  if [ -n "$py" ]; then by_python[$py]+="${by_python[$py]:+,}$h"; os_of[$h]=$os; else current+=("$h"); fi
done

if ((${#current[@]})); then
  ansible-playbook "$PLAYBOOK" -l "$(IFS=,; echo "${current[*]}")" "$@"
fi

if ((${#by_python[@]})); then
  [ -x "$LEGACY_BIN/ansible-playbook" ] || { echo "ERROR: $LEGACY_BIN/ansible-playbook missing (needed for ${!os_of[*]}). See README.md."; exit 1; }
  ANSIBLE_COLLECTIONS_PATH=./collections-el7 "$LEGACY_BIN/ansible-galaxy" collection install -r collections/requirements-el7.yml -p ./collections-el7
  for py in "${!by_python[@]}"; do
    hosts=${by_python[$py]}
    echo "===== $hosts ($(for h in ${hosts//,/ }; do printf '%s ' "${os_of[$h]}"; done| xargs)): $("$LEGACY_BIN/ansible" --version | head -1), Python $py"
    ANSIBLE_COLLECTIONS_PATH=./collections-el7 "$LEGACY_BIN/ansible-playbook" "$PLAYBOOK" \
      -l "$hosts" -e ansible_python_interpreter="$py" "$@"
  done
fi
