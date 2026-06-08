"""
Host IP Heartbeat — runs in background thread
Checks all host IPs every 10 minutes and restores if lost
Covers base hosts + all tenant hosts
"""
import threading
import time
import json
import os

def get_all_expected_hosts():
    """Get base hosts + tenant hosts from tenants.json."""
    hosts = [
        ("Admin",          "192.168.10.10/24", "192.168.10.1"),
        ("HStore",         "192.168.20.10/24", "192.168.20.1"),
        ("WiFi",           "192.168.30.10/24", "192.168.30.1"),
        ("CCTV",           "192.168.40.10/24", "192.168.40.1"),
        ("PaymentServers", "192.168.50.10/24", "192.168.50.1"),
    ]
    # Add tenant hosts from tenants.json
    try:
        with open("tenants.json") as f:
            tenants = json.load(f)
        for tenant_name, record in tenants.items():
            config = record.get("config", {})
            gateway = config.get("gateway", "")
            vlan_id = config.get("vlan_id", "")
            num_hosts = config.get("num_hosts", 0)
            base_ip = ".".join(gateway.split(".")[:3]) if gateway else ""

            # Use hosts list if available
            host_list = record.get("hosts", [])
            if host_list:
                for host in host_list:
                    ip = host.get("ip", "")
                    host_name = host.get("host", "")
                    if ip and gateway and host_name:
                        # Ensure /24 suffix
                        if "/" not in ip:
                            ip = ip + "/24"
                        hosts.append((host_name, ip, gateway))
            elif base_ip and num_hosts:
                # Reconstruct from config
                for i in range(num_hosts):
                    host_name = tenant_name if num_hosts == 1 else f"{tenant_name}_{i+1}"
                    host_ip = f"{base_ip}.{10+i}/24"
                    hosts.append((host_name, host_ip, gateway))
    except Exception as e:
        print(f"[HEARTBEAT] Could not load tenant hosts: {e}")
    return hosts

def check_host_ip(port, expected_ip, topology):
    """Check if a host has the expected IP."""
    try:
        from host_manager import send_docker_command
        output = send_docker_command(port, "ip addr show eth0", wait=3)
        ip = expected_ip.split("/")[0]
        return ip in output
    except:
        return False

def restore_host_ip(host_name, ip_cidr, gateway, topology):
    """Restore IP on a host."""
    try:
        from host_manager import set_host_ip
        result = set_host_ip(host_name, ip_cidr, gateway, topology)
        return result["status"] == "success"
    except:
        return False

def run_heartbeat():
    """Main heartbeat loop — checks every 10 minutes."""
    print("[HEARTBEAT] Starting host IP heartbeat monitor...")
    while True:
        time.sleep(600)  # Check every 10 minutes
        try:
            from host_manager import load_topology, get_node
            topology = load_topology()
            hosts = get_all_expected_hosts()
            restored = []
            failed = []

            for host_name, ip_cidr, gateway in hosts:
                node = get_node(topology, host_name)
                if not node:
                    continue
                port = node["console_port"]
                if not check_host_ip(port, ip_cidr, topology):
                    print(f"[HEARTBEAT] {host_name} lost IP {ip_cidr} — restoring...")
                    ok = restore_host_ip(host_name, ip_cidr, gateway, topology)
                    if ok:
                        restored.append(host_name)
                        print(f"[HEARTBEAT] ✅ {host_name} restored")
                    else:
                        failed.append(host_name)
                        print(f"[HEARTBEAT] ❌ {host_name} restore failed")

            if restored:
                print(f"[HEARTBEAT] Restored {len(restored)} host(s): {restored}")
            if failed:
                print(f"[HEARTBEAT] Failed {len(failed)} host(s): {failed}")
            if not restored and not failed:
                print(f"[HEARTBEAT] All {len(hosts)} hosts have correct IPs")

        except Exception as e:
            print(f"[HEARTBEAT] Error: {e}")

def start_heartbeat():
    """Start heartbeat in background thread."""
    t = threading.Thread(target=run_heartbeat, daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    print("Testing heartbeat...")
    from host_manager import load_topology, get_node
    topology = load_topology()
    hosts = get_all_expected_hosts()
    print(f"Monitoring {len(hosts)} hosts:")
    for name, ip, gw in hosts:
        node = get_node(topology, name)
        status = "found" if node else "NOT IN TOPOLOGY"
        print(f"  {name:20} {ip:20} {status}")
