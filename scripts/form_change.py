#!/usr/bin/env python3
"""Apply a Jenkins form request to inventory/hosts.yml and host_vars/<name>.yml.

Usage:
  form_change.py --family linux --name client01 --ip 172.20.119.111 --os Ubuntu-24 \
                 --ssh-port 22 --cred-id client-client01 --add rules_add.txt
  form_change.py --family linux --name client01 --ip 172.20.119.111 --existing \
                 --cred-id client-client01 --remove rules_remove.txt

--family: the Jenkins job's OS family; a client of the other family is refused.
--os / --ssh-port left out: keep the client's current values (a new client needs --os; SSH port 22).
--existing: the client must already be in the inventory with this IP (the Remove jobs).

Rule files: one rule per line, blank lines and lines starting with # are ignored.
  SOURCE DESTINATION PORTS [PROTO] [COMMENT...]
  172.20.120.0/24  any  80,443  tcp  Web from app subnet
  any  172.20.119.111  8000-8010  udp  App ports
SOURCE / DESTINATION: any, an IP or a CIDR. PORTS: 443, 8000-8010 or 80,443. PROTO: tcp (default) or udp.

Exit 0 = files changed, 10 = nothing to change, 1 = invalid request.
No secret is ever written: the host only names its Jenkins credential and the
environment variables the pipelines fill from it.
"""
import argparse
import ipaddress
import json
import re
import sys

import yaml

OS_TYPES = ["AlmaLinux-10", "AlmaLinux-8", "AlmaLinux-9", "CentOS-10", "CentOS-7", "CentOS-8", "CentOS-9", "OracleLinux-10", "OracleLinux-7", "OracleLinux-8", "OracleLinux-9", "RedHat-10", "RedHat-7", "RedHat-8", "RedHat-9", "Rocky-10", "Rocky-8", "Rocky-9", "Ubuntu-20", "Ubuntu-22", "Ubuntu-24", "Ubuntu-26", "Windows-2019", "Windows-2022", "Windows-2025"]
HOSTS_FILE = "inventory/hosts.yml"


def fail(msg):
    sys.exit(f"ERROR: {msg}")


def cred_env(name):
    """Environment-variable prefix the pipelines use for this host's credential."""
    return "FWCRED_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def check_addr(value, what):
    if value == "any":
        return value
    try:
        return str(ipaddress.ip_network(value, strict=False)) if "/" in value else str(ipaddress.ip_address(value))
    except ValueError:
        fail(f"{what}: {value!r} is not 'any', an IP address or a CIDR")


def check_port(value, what):
    m = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", value)
    if not m or any(int(p) > 65535 or int(p) < 1 for p in m.groups() if p):
        fail(f"{what}: bad port {value!r} (use 443 or 8000-8010, 1-65535)")
    if m.group(2) and int(m.group(2)) <= int(m.group(1)):
        fail(f"{what}: port range {value!r} must go from low to high")
    return int(value) if not m.group(2) else value


def parse_rules(path, default_comment):
    rules = []
    if not path:
        return rules
    with open(path) as f:
        lines = f.read().splitlines()
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        where = f"{path} line {n} ({line!r})"
        if len(parts) < 3:
            fail(f"{where}: need at least SOURCE DESTINATION PORTS")
        src, dst, ports = parts[0].lower(), parts[1].lower(), parts[2]
        proto, rest = "tcp", parts[3:]
        if rest and rest[0].lower() in ("tcp", "udp"):
            proto, rest = rest[0].lower(), rest[1:]
        comment = " ".join(rest) or default_comment
        src, dst = check_addr(src, where), check_addr(dst, where)
        for p in [p for p in ports.split(",") if p]:
            rules.append({"port": check_port(p, where), "proto": proto, "src": src, "dst": dst, "comment": comment})
    return rules


def key(rule):
    return (str(rule["port"]), str(rule.get("proto", "tcp")).lower(), str(rule.get("src", "any")), str(rule.get("dst", "any")))


def split_header(path):
    """Leading comment / '---' lines (kept verbatim) and the YAML data."""
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        return None, None
    header = []
    for line in text.splitlines():
        if line.startswith("#") or line.strip() in ("", "---"):
            header.append(line)
        else:
            break
    return "\n".join(header).rstrip() + "\n", yaml.safe_load(text) or {}


def rule_line(r):
    port = r["port"] if isinstance(r["port"], int) else json.dumps(str(r["port"]))
    return (f"  - {{port: {port}, proto: {r.get('proto', 'tcp')}, src: {r.get('src', 'any')}, "
            f"dst: {r.get('dst', 'any')}, comment: {json.dumps(str(r['comment']))}}}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--ip", required=True)
    ap.add_argument("--family", required=True, choices=["linux", "windows"])
    ap.add_argument("--os", choices=OS_TYPES)
    ap.add_argument("--ssh-port")
    ap.add_argument("--existing", action="store_true")
    ap.add_argument("--cred-id", required=True)
    ap.add_argument("--add")
    ap.add_argument("--remove")
    ap.add_argument("--requested-by", default="Jenkins form")
    a = ap.parse_args()

    name = a.name.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name):
        fail(f"client name {a.name!r}: use lowercase letters, digits and '-' (max 63)")
    ip = check_addr(a.ip.strip(), "client IP")
    if ip == "any" or "/" in ip:
        fail(f"client IP {a.ip!r} must be a single IP address")
    group = a.family

    # ---- inventory -------------------------------------------------------------------------
    header, inv = split_header(HOSTS_FILE)
    if inv is None:
        fail(f"{HOSTS_FILE} not found (run from the repo root)")
    children = inv.setdefault("all", {}).setdefault("children", {})
    for g in ("linux", "windows"):
        grp = children.setdefault(g, {}) or {}
        children[g] = grp
        if not grp.get("hosts"):
            grp["hosts"] = {}
    for g, grp in children.items():
        for h, hv in (grp.get("hosts") or {}).items():
            if h != name and (hv or {}).get("ansible_host") == ip:
                fail(f"IP {ip} is already used by host {h!r} in group {g}")
    old_group = next((g for g, grp in children.items() if name in (grp.get("hosts") or {})), None)
    if old_group and old_group != group:
        fail(f"{name} is a {old_group} client: use the {old_group.capitalize()} jobs")
    if a.existing and not old_group:
        fail(f"{name} is not a known client: add it with the {group.capitalize()} Open job first")
    hostvars = dict(children[old_group]["hosts"].pop(name) or {}) if old_group else {}
    if a.existing and hostvars.get("ansible_host") != ip:
        fail(f"{name} has IP {hostvars.get('ansible_host')} in the inventory, not {ip}")

    if a.os and hostvars.get("os_baseline") and a.os != hostvars["os_baseline"]:
        fail(f"{name} is {hostvars['os_baseline']} in the inventory, not {a.os}: choose {hostvars['os_baseline']} "
             "(if the client was reinstalled, change os_baseline in inventory/hosts.yml through a pull request)")
    os_type = a.os or hostvars.get("os_baseline")
    if not os_type:
        fail(f"{name} is a new client: choose its OS")
    if (group == "windows") != os_type.startswith("Windows"):
        fail(f"OS {os_type} is not a {group} OS")
    ssh_port = check_port(str(a.ssh_port or hostvars.get("fw_ssh_port") or 22).strip(), "SSH port")
    if not isinstance(ssh_port, int):
        fail("the SSH port must be a single port")

    env = cred_env(name)
    hostvars.update({"ansible_host": ip, "os_baseline": os_type, "fw_cred_id": a.cred_id,
                     "ansible_user": f'{{{{ lookup("env", "{env}_USER") }}}}',
                     "ansible_password": f'{{{{ lookup("env", "{env}_PASS") }}}}'})
    for k in ("ansible_port", "fw_ssh_port", "fw_rdp_port", "ansible_become_password"):
        hostvars.pop(k, None)
    if group == "linux":
        hostvars.update({"ansible_port": ssh_port, "fw_ssh_port": ssh_port,
                         "ansible_become_password": f'{{{{ lookup("env", "{env}_PASS") }}}}'})
    children[group]["hosts"][name] = hostvars
    for g in children:
        children[g]["hosts"] = dict(sorted(children[g]["hosts"].items()))

    # ---- host rules ------------------------------------------------------------------------
    hv_path = f"host_vars/{name}.yml"
    hv_header, hv = split_header(hv_path)
    if hv is None:
        hv_header = f"---\n# Firewall rules for {name}. Edit through the Jenkins form or a pull request.\n"
        hv = {}
    rules = list(hv.get("fw_rules") or [])
    current = {key(r): r for r in rules}
    adds = parse_rules(a.add, f"Added via Jenkins by {a.requested_by}")
    removes = parse_rules(a.remove, "remove")
    for r in removes:
        if key(r) not in current:
            have = "\n".join("    " + rule_line(x).strip()[2:] for x in rules) or "    (none)"
            fail(f"cannot remove {key(r)}: {name} has no such rule. Current rules:\n{have}")
        rules.remove(current.pop(key(r)))
    for r in adds:
        if key(r) in current:
            print(f"NOTE: rule {key(r)} already exists on {name}, skipped")
            continue
        rules.append(r)
        current[key(r)] = r

    # ---- write -----------------------------------------------------------------------------
    with open(HOSTS_FILE) as f:
        before_inv = f.read()
    new_inv = header + yaml.safe_dump(inv, sort_keys=False, default_flow_style=False, width=200)
    try:
        with open(hv_path) as f:
            before_hv = f.read()
    except FileNotFoundError:
        before_hv = None
    other = {k: v for k, v in hv.items() if k != "fw_rules"}
    body = "fw_rules:\n" + "\n".join(rule_line(r) for r in rules) + "\n" if rules else "fw_rules: []\n"
    new_hv = hv_header + (yaml.safe_dump(other, sort_keys=False, width=200) if other else "") + body

    if new_inv == before_inv and new_hv == before_hv:
        print(f"No changes for {name}.")
        sys.exit(10)
    with open(HOSTS_FILE, "w") as f:
        f.write(new_inv)
    with open(hv_path, "w") as f:
        f.write(new_hv)
    print(f"{name}: {len(adds)} rule(s) requested to add, {len(removes)} to remove; {len(rules)} rule(s) now on the host.")


if __name__ == "__main__":
    main()
