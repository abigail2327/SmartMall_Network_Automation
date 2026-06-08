"""
Closed Loop Correction Engine
Collects evidence → sends to Claude → applies delta fix → revalidates
"""
import json
import time
import os
import datetime
import anthropic
from config import GNS3_HOST, CISCO_SECRET, ANTHROPIC_API_KEY
from netmiko import ConnectHandler

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
# GNS3_HOST imported from config
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_device_ports():
    """Get console ports from topology.json — fallback to known defaults."""
    try:
        with open(os.path.join(BASE_DIR, "topology.json")) as f:
            topo = json.load(f)
        return {node["name"]: node["console_port"] for node in topo.get("nodes", [])}
    except:
        return {"R1": 5000, "R2": 5001, "SW1": 5002}

def connect_device(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST, port=port,
        username="", password=CISCO_SECRET, secret=CISCO_SECRET,
        timeout=60
    )

def safe_show(conn, cmd):
    try:
        conn.enable()
        return conn.send_command(cmd, delay_factor=2)
    except Exception as e:
        return f"ERROR: {e}"

def collect_evidence(scope="all"):
    """Collect diagnostic data scoped to what needs fixing."""
    evidence = {}
    port_map = get_device_ports()

    need_r1  = scope in ("all", "acls", "ospf", "routing")
    need_r2  = scope in ("all", "ospf")
    need_sw1 = scope in ("all", "vlans")

    if need_r1 and "R1" in port_map:
        try:
            print("  Collecting from R1...")
            conn = connect_device(port_map["R1"])
            conn.enable()
            evidence["R1_interfaces"] = safe_show(conn, "show ip interface brief")
            evidence["R1_routes"]     = safe_show(conn, "show ip route")
            if scope in ("all", "acls"):
                evidence["R1_acls"] = safe_show(conn, "show ip access-lists")
            if scope in ("all", "ospf"):
                evidence["R1_ospf"]        = safe_show(conn, "show ip ospf neighbor")
                evidence["R1_ospf_detail"] = safe_show(conn, "show ip ospf")
            conn.disconnect()
            print("  ✅ R1 done")
        except Exception as e:
            evidence["R1_error"] = str(e)
            print(f"  ❌ R1: {e}")

    if need_r2 and "R2" in port_map:
        try:
            print("  Collecting from R2...")
            conn = connect_device(port_map["R2"])
            conn.enable()
            evidence["R2_ospf"]   = safe_show(conn, "show ip ospf neighbor")
            evidence["R2_routes"] = safe_show(conn, "show ip route")
            conn.disconnect()
            print("  ✅ R2 done")
        except Exception as e:
            evidence["R2_error"] = str(e)
            print(f"  ⚠️  R2: {e}")

    if need_sw1 and "SW1" in port_map:
        try:
            print("  Collecting from SW1...")
            conn = connect_device(port_map["SW1"])
            conn.enable()
            evidence["SW1_vlans"] = safe_show(conn, "show vlan brief")
            evidence["SW1_trunk"] = safe_show(conn, "show interfaces trunk")
            conn.disconnect()
            print("  ✅ SW1 done")
        except Exception as e:
            evidence["SW1_error"] = str(e)
            print(f"  ❌ SW1: {e}")

    return evidence

def build_prompt(scope, failures, evidence):
    failure_list = json.dumps([f.get("description", "") for f in failures], indent=2)

    if scope in ("all", "acls"):
        acls       = evidence.get("R1_acls", "not collected")[:2000]
        interfaces = evidence.get("R1_interfaces", "not collected")[:800]
        context = f"""CURRENT ACL STATE ON R1:
{acls}

CURRENT INTERFACES:
{interfaces}

REQUIRED ACL POLICY:
- ACL 100 on FastEthernet0/0.10 (Admin):   permit ip any any
- ACL 120 on FastEthernet0/0.20 (HStore):  permit to 192.168.50.0/24, permit ip any any
- ACL 130 on FastEthernet0/0.30 (WiFi):    deny to 192.168.10.0/24, deny to 192.168.50.0/24, permit ip any any
- ACL 140 on FastEthernet0/0.40 (CCTV):    permit to 192.168.10.0/24, deny ip any any
- ACL 150 on FastEthernet0/0.50 (Payment): permit to 192.168.10.0/24, deny ip any any"""

    elif scope == "ospf":
        r1_ospf   = evidence.get("R1_ospf", "not collected")[:600]
        r2_ospf   = evidence.get("R2_ospf", "not collected")[:600]
        r1_detail = evidence.get("R1_ospf_detail", "")[:400]
        routes    = evidence.get("R1_routes", "not collected")[:600]
        context = f"""R1 OSPF NEIGHBORS:
{r1_ospf}

R2 OSPF NEIGHBORS:
{r2_ospf}

R1 OSPF DETAIL:
{r1_detail}

R1 ROUTES:
{routes}

BASELINE OSPF:
- Process 1, Area 0
- R1 router-id 1.1.1.1, R2 router-id 2.2.2.2
- Link 10.0.0.0/30: R1 FastEthernet0/1 ↔ R2 FastEthernet0/0
- R1 must advertise 192.168.10-50.0/24 subnets"""

    elif scope == "vlans":
        vlans      = evidence.get("SW1_vlans", "not collected")[:800]
        trunk      = evidence.get("SW1_trunk", "not collected")[:600]
        interfaces = evidence.get("R1_interfaces", "not collected")[:600]
        context = f"""SW1 VLAN BRIEF:
{vlans}

SW1 TRUNK:
{trunk}

R1 SUBINTERFACES:
{interfaces}

REQUIRED VLANs: 10 (Admin), 20 (HStore), 30 (WiFi), 40 (CCTV), 50 (Payment)
SW1 trunk port (Ethernet0/0) must carry all VLANs to R1"""

    else:
        snippet = {k: v[:400] for k, v in evidence.items()}
        context = f"EVIDENCE:\n{json.dumps(snippet, indent=2)[:3000]}"

    return f"""You are fixing a Cisco IOS network. Return ONLY valid JSON.

FAILED TESTS:
{failure_list}

{context}

Generate the MINIMAL Cisco IOS CLI commands to fix the listed failures.
- Delete and recreate ACLs with "no ip access-list extended X" first.
- End each block with "end" then "write memory".
- Only fix what is failing — do not touch working config.

Return ONLY this JSON (no markdown):
{{"diagnosis":"root cause in one sentence","fixes":[{{"device":"R1","commands":["conf t","...","end","write memory"],"reason":"what this fixes"}}],"confidence":"high|medium|low","warning":""}}

If nothing needs fixing: {{"diagnosis":"no issues found","fixes":[],"confidence":"high","warning":""}}"""

def ask_claude_for_fix(failures, evidence, scope="all"):
    prompt = build_prompt(scope, failures, evidence)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    print(f"  Claude: {raw[:200]}")

    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    else:
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s >= 0 and e > s:
            raw = raw[s:e]

    return json.loads(raw)

def apply_delta(fixes):
    port_map = get_device_ports()
    results = []
    for fix in fixes:
        device   = fix["device"]
        commands = fix["commands"]
        port     = port_map.get(device)
        if not port:
            print(f"  ⚠️  Unknown device: {device}")
            continue
        print(f"  Applying to {device}: {fix.get('reason', '')}")
        try:
            conn = connect_device(port)
            conn.enable()

            # Separate show/exec commands from config commands
            # Config mode starts after "conf t" and ends at "end"
            pre_cmds  = []
            cfg_cmds  = []
            post_cmds = []
            in_cfg = False
            for cmd in commands:
                cmd = cmd.strip()
                if not cmd:
                    continue
                if cmd.lower() in ("conf t", "configure terminal"):
                    in_cfg = True
                    continue
                if cmd.lower() == "end":
                    in_cfg = False
                    continue
                if in_cfg:
                    cfg_cmds.append(cmd)
                elif cmd.lower().startswith("write"):
                    post_cmds.append(cmd)
                else:
                    pre_cmds.append(cmd)

            for cmd in pre_cmds:
                conn.send_command_timing(cmd, delay_factor=2, read_timeout=30)

            if cfg_cmds:
                conn.send_config_set(
                    cfg_cmds,
                    cmd_verify=False,
                    delay_factor=2,
                    read_timeout=120,
                    enter_config_mode=True,
                    exit_config_mode=True
                )

            # Save config
            try:
                conn.send_command_timing("write memory", delay_factor=8, read_timeout=120)
            except:
                pass

            conn.disconnect()
            print(f"  ✅ {device} fixed")
            results.append({"device": device, "status": "success", "reason": fix.get("reason", "")})
        except Exception as e:
            print(f"  ❌ {device}: {e}")
            results.append({"device": device, "status": "error", "error": str(e)})
    return results

def run_quick_validation(scope="all"):
    """Quick validation — no iperf3, only checks relevant to scope."""
    from validate_network import run_router_checks, analyze_results
    from host_manager import load_topology, ping_from_host

    topology = load_topology()

    acl_tests = [
        ("Admin",          "192.168.20.10", "allow", "Admin → HStore"),
        ("Admin",          "192.168.50.10", "allow", "Admin → Payment"),
        ("Admin",          "192.168.30.10", "allow", "Admin → WiFi"),
        ("WiFi",           "192.168.10.10", "deny",  "WiFi → Admin (BLOCKED)"),
        ("WiFi",           "192.168.50.10", "deny",  "WiFi → Payment (BLOCKED)"),
        ("WiFi",           "192.168.20.10", "allow", "WiFi → HStore"),
        ("HStore",         "192.168.50.10", "allow", "HStore → Payment"),
        ("CCTV",           "192.168.10.10", "allow", "CCTV → Admin"),
        ("CCTV",           "192.168.50.10", "deny",  "CCTV → Payment (BLOCKED)"),
        ("PaymentServers", "192.168.10.10", "allow", "Payment → Admin"),
    ]

    ping_results = []
    if scope in ("all", "acls"):
        print("  Running ACL ping tests...")
        for src, dst, expected, desc in acl_tests:
            result = ping_from_host(src, dst, topology)
            passed = result["success"] if expected == "allow" else (result.get("blocked") or not result["success"])
            result["pass"]        = passed
            result["description"] = desc
            result["expected"]    = expected
            ping_results.append(result)
            time.sleep(0.5)

    router_checks = {}
    if scope in ("all", "ospf", "vlans"):
        print("  Running router/switch checks...")
        router_checks = run_router_checks(topology)

    summary = analyze_results(ping_results, router_checks)

    report = {
        "timestamp":    datetime.datetime.now().isoformat(),
        "summary":      summary,
        "ping_tests":   ping_results,
        "iperf3_results": [],
        "router_checks": router_checks
    }

    with open(os.path.join(BASE_DIR, "validation_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    return report

def detect_failures(report, scope="all"):
    failures = []

    if scope in ("all", "acls"):
        for t in report.get("ping_tests", []):
            if not t.get("pass"):
                failures.append({
                    "description": t.get("description", ""),
                    "expected":    t.get("expected", ""),
                    "actual":      "reachable" if t.get("success") else "timeout",
                    "type":        "acl"
                })

    summary = report.get("summary", {})
    if scope in ("all", "ospf") and summary.get("ospf_status") == "fail":
        failures.append({"description": "OSPF not in FULL state", "type": "ospf"})
    if scope in ("all", "vlans") and summary.get("vlan_status") == "fail":
        failures.append({"description": "VLANs not configured correctly", "type": "vlan"})

    return failures

def is_full_outage(report):
    """OSPF + VLANs both failing = devices are unconfigured, need full deploy."""
    s = report.get("summary", {})
    return s.get("ospf_status") == "fail" and s.get("vlan_status") == "fail"

def build_baseline_configs():
    """Generate R1/R2/SW1 baseline configs directly from intent.json."""
    with open(os.path.join(BASE_DIR, "intent.json")) as f:
        intent = json.load(f)
    net  = intent["network"]
    ospf = net["ospf"]
    vlans = net["vlans"]

    vlan_acl = {"10": 100, "20": 120, "30": 130, "40": 140, "50": 150}
    iface_vlan = [("Ethernet0/0","10"),("Ethernet0/1","20"),("Ethernet0/2","30"),
                  ("Ethernet0/3","40"),("Ethernet1/0","50")]

    # ── SW1 ──────────────────────────────────────────────
    sw1 = ["hostname SW1"]
    for v in vlans:
        sw1 += [f"vlan {v['id']}", f" name {v['name']}"]
    for iface, vid in iface_vlan:
        sw1 += [f"interface {iface}",
                " switchport mode access",
                f" switchport access vlan {vid}",
                " no shutdown"]
    sw1 += ["interface Ethernet1/1",
            " switchport trunk encapsulation dot1q",
            " switchport mode trunk",
            " switchport trunk allowed vlan 10,20,30,40,50",
            " no shutdown"]

    # ── R1 ───────────────────────────────────────────────
    r1 = ["hostname R1", "ip routing",
          "interface FastEthernet0/0", " no ip address", " no shutdown"]
    for v in vlans:
        vid = v["id"]
        acl = vlan_acl.get(vid, int(vid) + 90)
        r1 += [f"interface FastEthernet0/0.{vid}",
               f" encapsulation dot1Q {vid}",
               f" ip address {v['gateway']} 255.255.255.0",
               f" ip access-group {acl} in",
               " no shutdown"]
    r1 += ["interface FastEthernet1/0",
           f" ip address {ospf['r1_link_ip']} 255.255.255.252",
           " no shutdown",
           "no ip access-list extended 100",
           "ip access-list extended 100",
           " permit ip any any",
           "no ip access-list extended 120",
           "ip access-list extended 120",
           " permit ip 192.168.20.0 0.0.0.255 192.168.50.0 0.0.0.255",
           " permit ip any any",
           "no ip access-list extended 130",
           "ip access-list extended 130",
           " permit icmp 192.168.30.0 0.0.0.255 any echo-reply",
           " deny ip 192.168.30.0 0.0.0.255 192.168.10.0 0.0.0.255",
           " deny ip 192.168.30.0 0.0.0.255 192.168.50.0 0.0.0.255",
           " permit ip any any",
           "no ip access-list extended 140",
           "ip access-list extended 140",
           " permit icmp 192.168.40.0 0.0.0.255 any echo-reply",
           " permit ip 192.168.40.0 0.0.0.255 192.168.10.0 0.0.0.255",
           " deny ip any any",
           "no ip access-list extended 150",
           "ip access-list extended 150",
           " permit icmp 192.168.50.0 0.0.0.255 any echo-reply",
           " permit ip 192.168.50.0 0.0.0.255 192.168.10.0 0.0.0.255",
           " permit ip 192.168.50.0 0.0.0.255 192.168.20.0 0.0.0.255",
           " deny ip any any",
           "router ospf 1",
           f" router-id {ospf['r1_router_id']}"]
    for v in vlans:
        base = ".".join(v["subnet"].split("/")[0].split(".")[:3]) + ".0"
        r1.append(f" network {base} {ospf['wildcard']} area 0")
    link_base = ospf["link_subnet"].split("/")[0]
    r1.append(f" network {link_base} 0.0.0.3 area 0")

    # ── R2 ───────────────────────────────────────────────
    r2 = ["hostname R2", "ip routing",
          "interface FastEthernet0/0",
          f" ip address {ospf['r2_link_ip']} 255.255.255.252",
          " no shutdown",
          "router ospf 1",
          f" router-id {ospf['r2_router_id']}",
          f" network {link_base} 0.0.0.3 area 0"]

    return {"SW1": sw1, "R1": r1, "R2": r2}

def run_full_deploy():
    """Deploy complete baseline config to SW1, R1, R2."""
    print("  Building baseline configs from intent.json...")
    try:
        configs  = build_baseline_configs()
    except Exception as e:
        print(f"  ❌ Config build failed: {e}")
        return False

    port_map = get_device_ports()
    success  = True

    for device in ["SW1", "R1", "R2"]:
        port = port_map.get(device)
        if not port:
            print(f"  ⚠️  {device} not in topology")
            continue
        cmds = configs.get(device, [])
        print(f"  Deploying {device} ({len(cmds)} commands)...")
        try:
            conn = connect_device(port)
            conn.enable()
            conn.send_config_set(cmds, cmd_verify=False, delay_factor=2, read_timeout=120)
            conn.send_command_timing("write memory", delay_factor=8, read_timeout=120)
            conn.disconnect()
            print(f"  ✅ {device} deployed")
        except Exception as e:
            print(f"  ❌ {device}: {e}")
            success = False

    print("  Waiting 35s for OSPF convergence...")
    time.sleep(35)
    return success

def is_host_ip_lost(failures):
    """True when all ACL-type failures are timeouts — IPs lost, not an ACL mis-rule."""
    acl_failures = [f for f in failures if f.get("type") == "acl"]
    if not acl_failures:
        return False
    timeout_count = sum(1 for f in acl_failures if f.get("actual") == "timeout")
    return timeout_count == len(acl_failures) and timeout_count >= 3

def restore_host_ips():
    """Re-apply IPs to all base hosts and tenant hosts."""
    print("  Restoring host IPs (base + tenants)...")
    try:
        from host_manager import load_topology, configure_all_hosts
        import json as _json
        topology = load_topology()
        with open(os.path.join(BASE_DIR, "intent.json")) as f:
            intent = _json.load(f)
        results = configure_all_hosts(topology, intent)
        ok = sum(1 for r in results if r.get("status") == "success")
        print(f"  ✅ {ok}/{len(results)} base hosts restored")

        # Tenant hosts
        try:
            from host_manager import set_host_ip
            with open(os.path.join(BASE_DIR, "tenants.json")) as f:
                tenants = _json.load(f)
            for tname, rec in tenants.items():
                cfg  = rec.get("config", {})
                gw   = cfg.get("gateway", "")
                for h in rec.get("hosts", []):
                    ip = h.get("ip", "")
                    if ip and gw:
                        if "/" not in ip:
                            ip += "/24"
                        set_host_ip(h.get("host", tname), ip, gw, topology)
        except Exception as e:
            print(f"  ⚠️  Tenant host restore: {e}")

        return True
    except Exception as e:
        print(f"  ❌ Host IP restore failed: {e}")
        return False

def run_correction(scope="all", max_retries=3):
    print(f"\n{'='*50}")
    print(f"CLOSED LOOP CORRECTION (scope={scope})")
    print(f"{'='*50}")

    correction_log = {
        "scope":      scope,
        "started_at": datetime.datetime.now().isoformat(),
        "attempts":   [],
        "final_status": "unknown"
    }

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Attempt {attempt}/{max_retries} ---")

        print(f"[{attempt}] Validating (scope={scope})...")
        report   = run_quick_validation(scope)
        failures = detect_failures(report, scope)

        print(f"[{attempt}] Failures: {len(failures)}")
        for f in failures:
            print(f"  - {f['description']}")

        attempt_log = {
            "attempt":      attempt,
            "failures":     failures,
            "ping_summary": report["summary"].get("ping_tests", {})
        }

        if len(failures) == 0:
            print(f"\n✅ All checks passed on attempt {attempt}!")
            correction_log["final_status"] = "success"
            correction_log["attempts"].append(attempt_log)
            save_log(correction_log)
            return {
                "status":   "success",
                "attempts": attempt,
                "message":  f"All checks passed after {attempt} attempt(s).",
                "report":   report
            }

        # Full outage: OSPF + VLANs both down = devices need full baseline deploy
        if is_full_outage(report):
            print(f"[{attempt}] Full outage — OSPF+VLANs down. Deploying baseline config...")
            ok = run_full_deploy()
            attempt_log["full_deploy"] = ok
            # After deploy, restore host IPs too
            restore_host_ips()
            time.sleep(5)
            correction_log["attempts"].append(attempt_log)
            continue

        # All ACL tests timing out but infra is up = hosts lost their IPs
        if is_host_ip_lost(failures):
            print(f"[{attempt}] All ping failures are timeouts — restoring host IPs...")
            attempt_log["host_ip_restore"] = restore_host_ips()
            correction_log["attempts"].append(attempt_log)
            time.sleep(10)
            continue

        print(f"[{attempt}] Collecting evidence...")
        evidence = collect_evidence(scope)

        print(f"[{attempt}] Asking Claude for fix plan...")
        try:
            fix_plan = ask_claude_for_fix(failures, evidence, scope)
            print(f"  Diagnosis:  {fix_plan.get('diagnosis', '')[:100]}")
            print(f"  Confidence: {fix_plan.get('confidence', '?')}")
            print(f"  Fixes:      {len(fix_plan.get('fixes', []))}")

            attempt_log["diagnosis"]  = fix_plan.get("diagnosis")
            attempt_log["confidence"] = fix_plan.get("confidence")

            if fix_plan.get("fixes"):
                apply_results = apply_delta(fix_plan["fixes"])
                attempt_log["applied"] = apply_results
                time.sleep(8)
            else:
                print("  No fixes needed per Claude — may be transient")

        except Exception as e:
            print(f"  Fix error: {e}")
            attempt_log["error"] = str(e)

        correction_log["attempts"].append(attempt_log)

    # Final check after all retries exhausted
    print("\n[FINAL] Running last validation pass...")
    final_report   = run_quick_validation(scope)
    final_failures = detect_failures(final_report, scope)

    if len(final_failures) == 0:
        correction_log["final_status"] = "success"
        save_log(correction_log)
        return {
            "status":   "success",
            "attempts": max_retries,
            "message":  f"All checks passed after {max_retries} attempt(s).",
            "report":   final_report
        }

    correction_log["final_status"] = "partial"
    save_log(correction_log)
    return {
        "status":   "partial",
        "attempts": max_retries,
        "message":  f"{len(final_failures)} issue(s) remain after {max_retries} attempt(s). Manual review may be needed.",
        "log":      correction_log
    }

def save_log(log):
    log["timestamp"] = datetime.datetime.now().isoformat()
    with open(os.path.join(BASE_DIR, "correction_log.json"), "w") as f:
        json.dump(log, f, indent=2)

if __name__ == "__main__":
    result = run_correction(scope="all", max_retries=2)
    print(f"\nResult: {result['status']} — {result['message']}")
