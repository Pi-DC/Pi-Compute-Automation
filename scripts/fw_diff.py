#!/usr/bin/env python3
"""Rule plan for one host: (old baseline + old host file) vs (new baseline + new host file).

Usage: fw_diff.py --old [files...] --new file [file...]
Exit 0 = plan printed as YAML (fw_add / fw_remove), 10 = nothing to change, 1 = invalid rule.
"""
import argparse
import ipaddress
import re
import sys

import yaml


def load(paths):
    rules = []
    for p in paths:
        with open(p) as f:
            rules += (yaml.safe_load(f) or {}).get("fw_rules") or []
    return rules


def key(rule, where):
    port = str(rule.get("port", ""))
    proto = str(rule.get("proto", "")).lower()
    src = str(rule.get("src", ""))
    dst = str(rule.get("dst", "any"))
    if not re.fullmatch(r"\d{1,5}(-\d{1,5})?", port) or any(int(p) > 65535 for p in port.split("-")):
        sys.exit(f"{where}: bad port {port!r} in {rule}")
    if proto not in ("tcp", "udp"):
        sys.exit(f"{where}: proto must be tcp or udp, got {proto!r} in {rule}")
    for field, value in (("src", src), ("dst", dst)):
        if value != "any":
            try:
                ipaddress.ip_network(value, strict=False)
            except ValueError:
                sys.exit(f"{where}: bad {field} {value!r} in {rule}")
    if not rule.get("comment"):
        sys.exit(f"{where}: every rule needs a comment: {rule}")
    return (port, proto, src, dst)


ap = argparse.ArgumentParser()
ap.add_argument("--old", nargs="*", default=[])
ap.add_argument("--new", nargs="+", required=True)
args = ap.parse_args()

old = {key(r, "old"): r for r in load(args.old)}
new = {key(r, "new"): r for r in load(args.new)}
plan = {
    "fw_add": [new[k] for k in sorted(new.keys() - old.keys())],
    "fw_remove": [old[k] for k in sorted(old.keys() - new.keys())],
}
if not plan["fw_add"] and not plan["fw_remove"]:
    sys.exit(10)
yaml.safe_dump(plan, sys.stdout, sort_keys=False)
