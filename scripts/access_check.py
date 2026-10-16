#!/usr/bin/env python3
"""No rule is added by default, so a client's own rules must keep Ansible's access to it.

  access_check.py <host> [<host>...]     (run from the repo root; scripts/plan.sh runs it for every host)

For each host: some rule in baselines/<os_baseline>.yml + host_vars/<host>.yml must allow tcp from the Jenkins
agent (fw_agent_ip in inventory/group_vars/all.yml) to the host's connection port (ansible_port: the SSH port on
Linux, WinRM 5986 on Windows): source any or a network containing the agent, destination any or a network
containing the host's address. Otherwise switching the firewall on, or removing that rule, would lock Jenkins out.
Exit 0 = every host keeps access, 1 = at least one would not (ERROR lines say which rule to add).
"""
import ipaddress
import json
import subprocess
import sys

import yaml


def rules(path):
    try:
        with open(path) as f:
            return (yaml.safe_load(f) or {}).get("fw_rules") or []
    except FileNotFoundError:
        return []


def in_net(addr, net):
    return net == "any" or ipaddress.ip_address(addr) in ipaddress.ip_network(str(net), strict=False)


def port_ok(rule_port, port):
    lo, _, hi = str(rule_port).partition("-")
    return int(lo) <= port <= int(hi or lo)


def main():
    with open("inventory/group_vars/all.yml") as f:
        agent = yaml.safe_load(f)["fw_agent_ip"]
    bad = False
    for host in sys.argv[1:]:
        hv = json.loads(subprocess.run(["ansible-inventory", "-i", "inventory/hosts.yml", "--host", host],
                                       check=True, capture_output=True, text=True).stdout)
        is_windows = str(hv.get("os_baseline", "")).startswith("Windows")
        port = int(hv.get("ansible_port") or (5986 if is_windows else 22))
        what = "WinRM" if is_windows else "SSH"
        addr = hv["ansible_host"]
        have = rules(f"baselines/{hv.get('os_baseline')}.yml") + rules(f"host_vars/{host}.yml")
        ok = [r for r in have if str(r.get("proto", "tcp")).lower() == "tcp" and port_ok(r["port"], port)
              and in_net(agent, r.get("src", "any")) and in_net(addr, r.get("dst", "any"))]
        if ok:
            r = ok[0]
            print(f"{host}: Jenkins agent {agent} reaches {what} port {port} via rule "
                  f"{r.get('src', 'any')} -> {r.get('dst', 'any')} {r['port']}/tcp ({r.get('comment', '')})")
        else:
            bad = True
            print(f"ERROR: {host}: no rule lets the Jenkins agent {agent} reach {what} port {port}/tcp, so Jenkins would lose "
                  f"access to it once its firewall is on. No rule is added by default: keep that rule, or add one, e.g. "
                  f"'{agent} any {port} tcp Jenkins {what}' (or a subnet that contains {agent}).")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
