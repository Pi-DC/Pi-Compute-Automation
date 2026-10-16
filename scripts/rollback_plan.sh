#!/usr/bin/env bash
# Plans that take hosts back from the rules of commit FROM to the rules of commit TO.
#   scripts/rollback_plan.sh <FROM> <TO> <host,host,...>
# Run in a checkout of FROM (its inventory still lists every host). A host that does not exist in TO
# (it was added by FROM) gets all its rules removed. The firewall itself stays enabled and the protected
# management rules stay. Writes plans/<host>.yml for each host that has something to undo.
set -euo pipefail
FROM=$1 TO=$2 HOSTS=$3
rm -rf plans prev && mkdir -p plans prev
printf 'fw_rules: []\n' > prev/empty.yml

for h in ${HOSTS//,/ }; do
  os=$(ansible-inventory -i inventory/hosts.yml --host "$h" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("os_baseline", ""))')
  old=() new=()
  for f in "baselines/$os.yml" "host_vars/$h.yml"; do
    p="prev/from-$h-$(basename "$f")"; git show "$FROM:$f" > "$p" 2>/dev/null && old+=("$p")
    p="prev/to-$h-$(basename "$f")";   git show "$TO:$f"   > "$p" 2>/dev/null && new+=("$p")
  done
  git cat-file -e "$TO:host_vars/$h.yml" 2>/dev/null || new=(prev/empty.yml)

  rc=0
  python3 scripts/fw_diff.py --old "${old[@]}" --new "${new[@]}" > "plans/$h.yml" || rc=$?
  case $rc in
    0)  echo "$h" >> plans/hosts.txt; echo "===== $h: rollback plan"; cat "plans/$h.yml" ;;
    10) rm -f "plans/$h.yml"; echo "===== $h: no rules to undo" ;;
    *)  exit 1 ;;
  esac
done
