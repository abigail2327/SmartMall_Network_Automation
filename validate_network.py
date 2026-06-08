import json
import time
import datetime
import socket
from netmiko import ConnectHandler
from config import GNS3_HOST, CISCO_SECRET
from host_manager import (
    load_topology, ping_from_host, get_node,
    run_iperf3_server, run_iperf3_client
)


def connect_router(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST,
        port=port,
        username="",
        password="",
        secret=CISCO_SECRET,
        timeout=120
    )

def safe_cmd(conn, cmd, delay=2):
    """Send command safely — ensure we're in enable mode first."""
    try:
        conn.enable()
        out = conn.send_command(cmd, delay_factor=delay)
        return out
    except Exception as e:
        return f"ERROR: {e}"

def run_router_checks(topology):
    results = {}
    r1_port = get_node(topology, "R1")["console_port"]
    r2_port = get_node(topology, "R2")["console_port"]
    sw1_port = get_node(topology, "SW1")["console_port"]

    try:
        print("  Checking R1...")
        r1 = connect_router(r1_port)
        r1.enable()
        time.sleep(1)
        results["r1_interfaces"] = safe_cmd(r1, "show ip interface brief")
        results["r1_routes"]     = safe_cmd(r1, "show ip route")
        results["r1_ospf"]       = safe_cmd(r1, "show ip ospf neighbor")
        results["r1_acls"]       = safe_cmd(r1, "show ip access-lists")
        results["r1_qos"]        = safe_cmd(r1, "show policy-map interface FastEthernet0/0")
        r1.disconnect()
        print("  ✅ R1 done")
    except Exception as e:
        results["r1_error"] = str(e)
        print(f"  ❌ R1 error: {e}")

    try:
        print("  Checking R2...")
        r2 = connect_router(r2_port)
        r2.enable()
        time.sleep(2)
        results["r2_ospf"]   = safe_cmd(r2, "show ip ospf neighbor", delay=3)
        results["r2_routes"] = safe_cmd(r2, "show ip route", delay=3)
        r2.disconnect()
        print("  ✅ R2 done")
    except Exception as e:
        results["r2_error"] = str(e)
        results["r2_ospf"] = ""
        print(f"  ⚠️  R2 skipped: {e}")

    try:
        print("  Checking SW1...")
        sw1 = connect_router(sw1_port)
        sw1.enable()
        time.sleep(1)
        results["sw1_vlans"] = safe_cmd(sw1, "show vlan brief")
        results["sw1_trunk"] = safe_cmd(sw1, "show interfaces trunk")
        sw1.disconnect()
        print("  ✅ SW1 done")
    except Exception as e:
        results["sw1_error"] = str(e)
        print(f"  ❌ SW1 error: {e}")

    return results

def run_iperf3_tests(topology):
    results = []
    print("  Starting iperf3 servers...")
    run_iperf3_server("PaymentServers", topology)
    run_iperf3_server("Admin", topology)
    time.sleep(4)

    iperf_tests = [
        ("HStore", "192.168.50.10", "HStore → Payment (high priority)"),
        ("WiFi",   "192.168.10.10", "WiFi → Admin (best effort — ACL blocked, N/A expected)"),
    ]
    for client, server_ip, desc in iperf_tests:
        print(f"  Running iperf3: {desc}...")
        result = run_iperf3_client(client, server_ip, topology, duration=5)
        if result:
            result["description"] = desc
            throughput = f"{result['throughput_mbps']:.2f} Mbps" if result.get("throughput_mbps") else "N/A (blocked)"
            print(f"  ✅ {desc} — {throughput}")
            results.append(result)
    return results

def analyze_results(ping_tests, router_checks):
    summary = {
        "ping_tests": {"total": 0, "passed": 0, "failed": 0},
        "vlan_status": "unknown",
        "ospf_status": "unknown",
        "routing_status": "unknown",
        "qos_status": "unknown",
        "acl_status": "unknown"
    }

    for test in ping_tests:
        summary["ping_tests"]["total"] += 1
        if test.get("pass"):
            summary["ping_tests"]["passed"] += 1
        else:
            summary["ping_tests"]["failed"] += 1

    # VLAN check
    vlans = router_checks.get("sw1_vlans", "")
    required_vlans = ["10", "20", "30", "40", "50"]
    summary["vlan_status"] = "pass" if all(
        f" {v} " in vlans or f"\n{v} " in vlans
        for v in required_vlans
    ) else "fail"

    # OSPF check — look for FULL anywhere in output
    ospf = router_checks.get("r1_ospf", "")
    summary["ospf_status"] = "pass" if "FULL" in ospf else "fail"
    if summary["ospf_status"] == "fail":
        print(f"  ⚠️  OSPF check failed — raw output: {ospf[:80]}")

    # Routing check
    routes = router_checks.get("r1_routes", "")
    required_networks = ["192.168.10", "192.168.20", "192.168.30", "192.168.40", "192.168.50"]
    summary["routing_status"] = "pass" if all(
        n in routes for n in required_networks
    ) else "fail"

    # QoS check
    qos = router_checks.get("r1_qos", "")
    summary["qos_status"] = "pass" if "CRITICAL" in qos or "policy-map" in qos.lower() else "partial"

    # ACL check
    acls = router_checks.get("r1_acls", "")
    summary["acl_status"] = "pass" if "Extended IP access list" in acls else "fail"

    return summary

def run_full_validation():
    print("=" * 50)
    print("SMARTMALL NETWORK VALIDATION")
    print("=" * 50)
    start_time = time.time()
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

    print("\n[1/4] Running ACL policy ping tests...")
    ping_results = []
    for src, dst, expected, desc in acl_tests:
        print(f"  Testing: {desc}...")
        result = ping_from_host(src, dst, topology)
        passed = result["success"] if expected == "allow" else (result["blocked"] or not result["success"])
        result["pass"] = passed
        result["description"] = desc
        result["expected"] = expected
        result["avg_latency"] = result.get("avg_latency_ms")
        icon = "✅" if passed else "❌"
        latency = f"{result.get('avg_latency_ms')}ms" if result.get("avg_latency_ms") else (
            "Blocked" if result.get("blocked") else "Timeout")
        print(f"  {icon} {desc} — {latency}")
        ping_results.append(result)
        time.sleep(1)

    print("\n[2/4] Running iperf3 tests...")
    iperf_results = run_iperf3_tests(topology)

    print("\n[3/4] Running router/switch verification...")
    router_checks = run_router_checks(topology)

    print("\n[4/4] Analyzing results...")
    summary = analyze_results(ping_results, router_checks)
    convergence_time = round(time.time() - start_time, 2)
    summary["convergence_time"] = convergence_time

    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "convergence_time_seconds": convergence_time,
        "summary": summary,
        "ping_tests": ping_results,
        "iperf3_results": iperf_results,
        "router_checks": router_checks
    }

    with open("validation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*50}")
    print("VALIDATION SUMMARY")
    print(f"{'='*50}")
    print(f"Ping tests: {summary['ping_tests']['passed']}/{summary['ping_tests']['total']} passed")
    print(f"VLANs:   {summary['vlan_status'].upper()}")
    print(f"OSPF:    {summary['ospf_status'].upper()}")
    print(f"Routing: {summary['routing_status'].upper()}")
    print(f"QoS:     {summary['qos_status'].upper()}")
    print(f"ACLs:    {summary['acl_status'].upper()}")
    for r in iperf_results:
        t = f"{r['throughput_mbps']:.2f} Mbps" if r.get("throughput_mbps") else "N/A"
        print(f"iperf3 {r['description']}: {t}")
    print(f"Time: {convergence_time}s")
    return report

if __name__ == "__main__":
    run_full_validation()
