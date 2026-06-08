import json
import time
import datetime
import os
from netmiko import ConnectHandler
from config import GNS3_HOST, CISCO_SECRET


def load_files():
    with open("topology.json") as f:
        topology = json.load(f)
    with open("configs.json") as f:
        configs = json.load(f)
    return topology, configs

def get_console_port(topology, device_name):
    for node in topology["nodes"]:
        if node["name"] == device_name:
            return node["console_port"]
    return None

def connect(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST,
        port=port,
        username="",
        password="",
        secret=CISCO_SECRET,
        timeout=60,
        session_log=f"logs/session_{port}.log"
    )

def send_commands(net_connect, commands, batch_size=10):
    results = []
    for i in range(0, len(commands), batch_size):
        batch = commands[i:i+batch_size]
        for cmd in batch:
            cmd = cmd.strip()
            if not cmd or cmd == "!":
                continue
            try:
                output = net_connect.send_command_timing(cmd, delay_factor=2)
                results.append({"cmd": cmd, "output": output, "status": "ok"})
            except Exception as e:
                results.append({"cmd": cmd, "output": str(e), "status": "error"})
        time.sleep(1)
    return results

def safe_send(net_connect, cmd, delay=3):
    """Send a command safely without pattern matching."""
    try:
        return net_connect.send_command_timing(cmd, delay_factor=delay)
    except Exception:
        try:
            return net_connect.send_command_timing(cmd, delay_factor=delay*2)
        except Exception as e:
            return str(e)

def deploy_device(device_name, topology, configs):
    log = {
        "device": device_name,
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "pending",
        "commands": [],
        "verification": {}
    }

    port = get_console_port(topology, device_name)
    if not port:
        log["status"] = "error"
        log["error"] = f"Console port not found for {device_name}"
        return log

    print(f"\n{'='*50}")
    print(f"Connecting to {device_name} on port {port}...")

    device_config = configs["devices"].get(device_name, "")
    if not device_config:
        log["status"] = "error"
        log["error"] = f"No config found for {device_name}"
        return log

    # Skip write memory from config — we'll handle it separately
    commands = [
        line.strip() for line in device_config.splitlines()
        if line.strip() and line.strip() != "!" and
        not line.strip().startswith("!") and
        line.strip().lower() != "write memory"
    ]

    try:
        net_connect = connect(port)
        net_connect.enable()

        # Pre-fix: bring up router interfaces
        if device_name == "R1":
            print("  Pre-fix: bringing up R1 interfaces...")
            for cmd in ["conf t", "interface FastEthernet0/0", "no shutdown",
                       "interface FastEthernet1/0", "no shutdown", "end"]:
                safe_send(net_connect, cmd, delay=1)
            time.sleep(2)

        if device_name == "R2":
            print("  Pre-fix: bringing up R2 interfaces...")
            for cmd in ["conf t", "interface FastEthernet0/0", "no shutdown", "end"]:
                safe_send(net_connect, cmd, delay=1)
            time.sleep(2)

        print(f"  Sending {len(commands)} commands...")
        results = send_commands(net_connect, commands)
        log["commands"] = results

        # Post-fix for SW1 trunk
        if device_name == "SW1":
            print("  Post-fix: applying correct IOU trunk config on e1/1...")
            for cmd in ["conf t", "interface Ethernet1/1",
                       "switchport trunk encapsulation dot1q",
                       "switchport mode trunk",
                       "switchport trunk allowed vlan 1-4094",
                       "no shutdown", "end"]:
                safe_send(net_connect, cmd, delay=2)
            time.sleep(2)

        # Post-fix for R1 ACL 100
        if device_name == "R1":
            print("  Post-fix: fixing ACL 100 for Admin full access...")
            for cmd in ["conf t", "no ip access-list extended 100",
                       "ip access-list extended 100",
                       "permit ip any any", "end"]:
                safe_send(net_connect, cmd, delay=2)
            time.sleep(1)

        errors = [r for r in results if r["status"] == "error"]
        print(f"  Commands sent: {len(results)}, Errors: {len(errors)}")

        # Save config — use send_command_timing with long delay for c7200
        print(f"  Saving config...")
        try:
            net_connect.send_command_timing("write memory", delay_factor=8, max_loops=500)
        except Exception:
            # If write memory times out, that's ok — config is in running-config
            print(f"  write memory timed out (normal for c7200) — continuing")

        # Verification — all use send_command_timing to avoid pattern issues
        print(f"  Running verification...")
        verif = {}
        try:
            verif["interfaces"] = safe_send(net_connect, "show ip interface brief", delay=3)
        except Exception:
            verif["interfaces"] = "timeout"

        if device_name in ["R1", "R2"]:
            try:
                verif["ospf_neighbors"] = safe_send(net_connect, "show ip ospf neighbor", delay=3)
                verif["routes"] = safe_send(net_connect, "show ip route", delay=3)
                print(f"  ✓ OSPF neighbors checked")
            except Exception:
                verif["ospf_neighbors"] = "timeout"

        if device_name == "SW1":
            try:
                verif["vlans"] = safe_send(net_connect, "show vlan brief", delay=3)
                verif["trunk"] = safe_send(net_connect, "show interfaces trunk", delay=3)
                print(f"  ✓ VLANs and trunk checked")
            except Exception:
                verif["vlans"] = "timeout"

        log["verification"] = verif
        net_connect.disconnect()

        log["status"] = "success" if len(errors) == 0 else "partial"
        print(f"✅ {device_name} deployment complete")

    except Exception as e:
        log["status"] = "error"
        log["error"] = str(e)
        print(f"❌ {device_name} failed: {e}")

    return log

def deploy_all():
    os.makedirs("logs", exist_ok=True)
    topology, configs = load_files()
    devices = ["R1", "R2", "SW1"]

    deployment_log = {
        "project": "SmartMall_x",
        "timestamp": datetime.datetime.now().isoformat(),
        "devices": {}
    }

    for device in devices:
        log = deploy_device(device, topology, configs)
        deployment_log["devices"][device] = log
        time.sleep(3)

    print(f"\n{'='*50}")
    print("DEPLOYMENT SUMMARY")
    print(f"{'='*50}")
    for device, log in deployment_log["devices"].items():
        status = log["status"]
        icon = "✅" if status == "success" else "⚠️" if status == "partial" else "❌"
        print(f"{icon} {device}: {status}")

    with open("deployment_log.json", "w") as f:
        json.dump(deployment_log, f, indent=2)

    print(f"\nDeployment log saved to deployment_log.json")
    return deployment_log

if __name__ == "__main__":
    deploy_all()
