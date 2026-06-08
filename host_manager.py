import socket
import time
import json
import re
from config import GNS3_HOST

_ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\x1b\][^\x07]*\x07|[\x08\x0e\x0f]')


def load_topology():
    with open("topology.json") as f:
        return json.load(f)

def get_node(topology, name):
    for node in topology["nodes"]:
        if node["name"] == name:
            return node
    return None

def get_docker_hosts(topology):
    return [n for n in topology["nodes"] if n["type"] == "docker"]

def get_routers(topology):
    return [n for n in topology["nodes"] if n["type"] == "dynamips"]

def get_switches(topology):
    return [n for n in topology["nodes"] if n["type"] == "iou"]

def send_docker_command(port, command, wait=5):
    """Send command to Docker host via raw socket with buffer drain."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(15)
        s.connect((GNS3_HOST, port))
        time.sleep(3)

        # Drain all pending data first
        s.settimeout(0.5)
        try:
            while True:
                data = s.recv(4096)
                if not data:
                    break
        except:
            pass

        # Send newline to get fresh prompt
        s.settimeout(3)
        s.sendall(b'\n')
        time.sleep(1)
        try:
            s.recv(4096)
        except:
            pass

        # Send actual command
        s.sendall(f"{command}\n".encode())
        time.sleep(wait)

        output = b""
        s.settimeout(2)
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                output += chunk
            except socket.timeout:
                break
        s.close()
        return output.decode("utf-8", errors="ignore")
    except Exception as e:
        return f"ERROR: {e}"

def set_host_ip(host_name, ip_cidr, gateway, topology):
    """Set static IP on a Docker host."""
    node = get_node(topology, host_name)
    if not node:
        return {"status": "error", "message": f"{host_name} not found"}
    port = node["console_port"]
    ip = ip_cidr.split("/")[0]

    print(f"  Setting {host_name} IP to {ip_cidr} gateway {gateway}...")
    # Flush all IPs first
    send_docker_command(port, "ip addr flush dev eth0", wait=3)
    send_docker_command(port, "ip link set eth0 up", wait=2)
    # Add new IP
    send_docker_command(port, f"ip addr add {ip_cidr} dev eth0", wait=2)
    # Set default route
    send_docker_command(port, "ip route del default 2>/dev/null || true", wait=2)
    send_docker_command(port, f"ip route add default via {gateway}", wait=2)

    verify = send_docker_command(port, "ip addr show eth0", wait=2)
    success = ip in verify
    print(f"  {'✅' if success else '❌'} {host_name}: {ip_cidr}")
    return {
        "status": "success" if success else "error",
        "host": host_name,
        "ip": ip_cidr,
        "gateway": gateway,
        "verify_output": verify
    }

def configure_all_hosts(topology, intent):
    """Set IPs on all Docker hosts based on intent.json."""
    vlans = intent["network"]["vlans"]
    host_vlan_map = {
        "Admin":          "10",
        "HStore":         "20",
        "WiFi":           "30",
        "CCTV":           "40",
        "PaymentServers": "50"
    }
    results = []
    for host_name, vlan_id in host_vlan_map.items():
        vlan = next((v for v in vlans if str(v["id"]) == vlan_id), None)
        if not vlan:
            continue
        gateway = vlan["gateway"]
        base = ".".join(gateway.split(".")[:3])
        host_ip = f"{base}.10/24"
        result = set_host_ip(host_name, host_ip, gateway, topology)
        results.append(result)
        time.sleep(1)
    return results

def ping_from_host(src_name, dst_ip, topology, count=5):
    """Run ping from a Docker host using raw socket."""
    node = get_node(topology, src_name)
    if not node:
        return {"src": src_name, "dst": dst_ip, "success": False,
                "blocked": False, "avg_latency_ms": None, "raw": "host not found"}
    port = node["console_port"]
    wait_time = count + 4
    output = send_docker_command(
        port,
        f"ping -c {count} -W 2 {dst_ip}",
        wait=wait_time
    )

    success = "bytes from" in output and "icmp_seq" in output
    blocked = "prohibited" in output or "filtered" in output.lower()

    avg_latency = None
    for line in output.splitlines():
        if ("rtt" in line or "avg" in line) and "/" in line:
            try:
                parts = line.split("=")[1].strip().split("/")
                avg_latency = float(parts[1])
            except:
                pass

    return {
        "src": src_name,
        "dst": dst_ip,
        "success": success,
        "blocked": blocked,
        "avg_latency_ms": avg_latency,
        "raw": output
    }

def run_iperf3_server(host_name, topology):
    """Start iperf3 server on a Docker host."""
    node = get_node(topology, host_name)
    if not node:
        return False
    port = node["console_port"]
    send_docker_command(port, "pkill -9 iperf3 2>/dev/null; sleep 1", wait=3)
    send_docker_command(port, "nohup iperf3 -s -p 5201 > /tmp/iperf3s.log 2>&1 &", wait=3)
    print(f"  ✅ iperf3 server started on {host_name}")
    return True

def run_iperf3_client(client_name, server_ip, topology, duration=5):
    """Run iperf3 client test from a Docker host."""
    node = get_node(topology, client_name)
    if not node:
        return None
    port = node["console_port"]
    output = send_docker_command(
        port,
        f"iperf3 -c {server_ip} -t {duration} -p 5201 --connect-timeout 3000",
        wait=duration + 5
    )

    clean_output = _ANSI_ESCAPE.sub('', output)
    import pathlib
    _log = pathlib.Path(__file__).parent / "iperf3_debug.log"
    with open(_log, "a") as _f:
        _f.write(f"\n=== {client_name} → {server_ip} ===\n")
        _f.write(f"RAW ({len(output)}b): {repr(output[:400])}\n")
        _f.write(f"CLEAN: {repr(clean_output[:400])}\n")
    print(f"  [iperf3 debug] raw ({len(output)} bytes): {repr(output[:300])}")
    print(f"  [iperf3 debug] clean: {repr(clean_output[:300])}")

    throughput = None
    for line in clean_output.splitlines():
        line = line.strip('\r')
        if "bits/sec" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if "bits/sec" in p and i > 0:
                    try:
                        val = float(parts[i-1])
                        if "Gbits" in p:
                            throughput = val * 1000
                        elif "Mbits" in p:
                            throughput = max(throughput or 0, val)
                        elif "Kbits" in p:
                            t = val / 1000
                            throughput = max(throughput or 0, t)
                    except:
                        pass

    print(f"  [iperf3 debug] parsed throughput: {throughput}")
    return {
        "client": client_name,
        "server_ip": server_ip,
        "throughput_mbps": throughput,
        "raw": output
    }

if __name__ == "__main__":
    print("Testing host_manager...")
    topology = load_topology()
    print("\nDocker hosts found:")
    for h in get_docker_hosts(topology):
        print(f"  {h['name']} — port {h['console_port']}")
    print("\nRouters found:")
    for r in get_routers(topology):
        print(f"  {r['name']} — port {r['console_port']}")
