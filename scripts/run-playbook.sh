#!/usr/bin/env bash
# Run a playbook on the given hosts, each with the Ansible that can manage it.
#   scripts/run-playbook.sh <playbook> <host,host,...> [ansible-playbook options...]
# CentOS 7 hosts (os_baseline in LEGACY_BASELINES) only have Python 2.7, which ansible-core 2.17 and
# later cannot manage. They run second, with ansible-core 2.16 from $FW_LEGACY_ANSIBLE and the
# collections in collections/requirements-el7.yml, using /usr/bin/python (it has the firewalld bindings).
# All other hosts run first, with the ansible-playbook on PATH. A failure stops before the next group.
set -euo pipefail
PLAYBOOK=$1 HOSTS=$2
shift 2
LEGACY_BASELINES=" CentOS-7 "
LEGACY_BIN=${FW_LEGACY_ANSIBLE:-/opt/ansible-el7/bin}

current=() legacy=()
for h in ${HOSTS//,/ }; do
  os=$(ansible-inventory -i inventory/hosts.yml --host "$h" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("os_baseline", ""))')
  if [[ $LEGACY_BASELINES == *" $os "* ]]; then legacy+=("$h"); else current+=("$h"); fi
done

if ((${#current[@]})); then
  ansible-playbook "$PLAYBOOK" -l "$(IFS=,; echo "${current[*]}")" "$@"
fi

if ((${#legacy[@]})); then
  [ -x "$LEGACY_BIN/ansible-playbook" ] || { echo "ERROR: $LEGACY_BIN/ansible-playbook missing (needed for ${legacy[*]}). See README.md."; exit 1; }
  echo "===== ${legacy[*]}: CentOS 7, $("$LEGACY_BIN/ansible" --version | head -1)"
  ANSIBLE_COLLECTIONS_PATH=./collections-el7 "$LEGACY_BIN/ansible-galaxy" collection install -r collections/requirements-el7.yml -p ./collections-el7
  ANSIBLE_COLLECTIONS_PATH=./collections-el7 "$LEGACY_BIN/ansible-playbook" "$PLAYBOOK" \
    -l "$(IFS=,; echo "${legacy[*]}")" -e ansible_python_interpreter=/usr/bin/python "$@"
fi
