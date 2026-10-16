#!/usr/bin/env bash
# Build per-host firewall plans.
#   scripts/plan.sh <base-commit | "">
# Writes plans/<host>.yml (fw_add / fw_remove) for every host whose rules changed
# since <base-commit>, and the list of those hosts in plans/hosts.txt.
# With an empty base (Day 1 / drift check) every rule counts as an add.
set -euo pipefail
BASE="${1:-}"
rm -rf plans prev && mkdir -p plans prev

inv() { ansible-inventory -i inventory/hosts.yml "$@"; }

hosts=$(inv --list | python3 -c 'import sys,json; print(" ".join(sorted(json.load(sys.stdin).get("_meta", {}).get("hostvars", {}))))')

for h in $hosts; do
  os=$(inv --host "$h" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("os_baseline", ""))')
  [ -n "$os" ]                || { echo "ERROR: $h has no os_baseline in inventory/hosts.yml"; exit 1; }
  [ -f "baselines/$os.yml" ]  || { echo "ERROR: baselines/$os.yml missing for $h"; exit 1; }
  [ -f "host_vars/$h.yml" ]   || { echo "ERROR: host_vars/$h.yml missing for $h"; exit 1; }
  # No rule is added by default: the host's own rules must keep Jenkins' access to it.
  python3 scripts/access_check.py "$h"

  new=("baselines/$os.yml" "host_vars/$h.yml")
  old=()
  if [ -n "$BASE" ]; then
    for f in "${new[@]}"; do
      p="prev/$h-$(basename "$f")"
      if git show "$BASE:$f" > "$p" 2>/dev/null; then old+=("$p"); fi
    done
  fi

  rc=0
  python3 scripts/fw_diff.py --old "${old[@]}" --new "${new[@]}" > "plans/$h.yml" || rc=$?
  case $rc in
    0)  echo "$h" >> plans/hosts.txt ;;
    10) rm -f "plans/$h.yml" ;;
    *)  exit 1 ;;
  esac
done

if [ -f plans/hosts.txt ]; then
  for h in $(cat plans/hosts.txt); do echo "===== $h"; cat "plans/$h.yml"; done
else
  echo "No firewall changes."
fi
