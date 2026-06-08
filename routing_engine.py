"""
Routing Protocol Engine
Handles OSPF config changes, RIPv2 migration, protocol switching
All via Claude Brain conversation
"""
from netmiko import ConnectHandler
from config import GNS3_HOST, CISCO_SECRET
import json
import time


def connect(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST, port=port,
        username="", password=CISCO_SECRET, secret=CISCO_SECRET,
        timeout=60
    )

def get_current_routing_config():
    """Get current routing protocol config from R1 and R2."""
    config = {}
    for device, port in [("R1", 5000), ("R2", 5001)]:
        try:
            conn = connect(port)
            conn.enable()
            config[device] = {
                "ospf": conn.send_command("show ip ospf"),
                "rip": conn.send_command("show ip rip"),
                "protocols": conn.send_command("show ip protocols"),
                "routes": conn.send_command("show ip route")
            }
            conn.disconnect()
        except Exception as e:
            config[device] = {"error": str(e)}
    return config

def change_ospf_config(changes):
    """
    Apply OSPF configuration changes.
    changes = {
        "r1_router_id": "3.3.3.3",
        "r2_router_id": "4.4.4.4",
        "area": "0",
        "process_id": "1"
    }
    """
    results = []

    # Load current intent
    with open("intent.json") as f:
        intent = json.load(f)

    ospf = intent["network"].get("ospf", {})

    for device, port in [("R1", 5000), ("R2", 5001)]:
        try:
            conn = connect(port)
            conn.enable()
            cmds = ["conf t"]

            # Change router ID
            if device == "R1" and changes.get("r1_router_id"):
                new_id = changes["r1_router_id"]
                cmds += [
                    f"router ospf {changes.get('process_id', 1)}",
                    f" router-id {new_id}",
                    " clear ip ospf process"
                ]
            elif device == "R2" and changes.get("r2_router_id"):
                new_id = changes["r2_router_id"]
                cmds += [
                    f"router ospf {changes.get('process_id', 1)}",
                    f" router-id {new_id}",
                    " clear ip ospf process"
                ]

            cmds.append("end")
            for cmd in cmds:
                conn.send_command_timing(cmd.strip(), delay_factor=2)
            conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
            conn.disconnect()
            print(f"  ✅ {device} OSPF updated")
            results.append({"device": device, "status": "success"})
        except Exception as e:
            print(f"  ❌ {device}: {e}")
            results.append({"device": device, "status": "error", "error": str(e)})

    # Update intent.json
    if changes.get("r1_router_id"):
        intent["network"]["ospf"]["r1_router_id"] = changes["r1_router_id"]
    if changes.get("r2_router_id"):
        intent["network"]["ospf"]["r2_router_id"] = changes["r2_router_id"]
    with open("intent.json", "w") as f:
        json.dump(intent, f, indent=2)

    return results

def migrate_to_ripv2():
    """Remove OSPF and configure RIPv2 on R1 and R2."""
    print("Migrating from OSPF to RIPv2...")

    with open("intent.json") as f:
        intent = json.load(f)

    vlans = intent["network"].get("vlans", [])
    results = []

    for device, port in [("R1", 5000), ("R2", 5001)]:
        try:
            conn = connect(port)
            conn.enable()

            cmds = [
                "conf t",
                # Remove OSPF
                "no router ospf 1",
                # Configure RIPv2
                "router rip",
                " version 2",
                " no auto-summary",
            ]

            # Add networks
            if device == "R1":
                for vlan in vlans:
                    subnet = vlan["subnet"].split("/")[0]
                    cmds.append(f" network {subnet}")
                cmds.append(" network 10.0.0.0")  # R1-R2 link

            elif device == "R2":
                cmds.append(" network 10.0.0.0")

            cmds.append("end")

            for cmd in cmds:
                conn.send_command_timing(cmd.strip(), delay_factor=2)
            conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
            conn.disconnect()
            print(f"  ✅ {device} migrated to RIPv2")
            results.append({"device": device, "status": "success"})
        except Exception as e:
            print(f"  ❌ {device}: {e}")
            results.append({"device": device, "status": "error", "error": str(e)})

    # Update intent.json
    intent["network"]["routing_protocol"] = "ripv2"
    with open("intent.json", "w") as f:
        json.dump(intent, f, indent=2)

    return results

def migrate_to_ospf():
    """Remove RIPv2 and restore OSPF on R1 and R2."""
    print("Migrating from RIPv2 to OSPF...")

    with open("intent.json") as f:
        intent = json.load(f)

    ospf = intent["network"].get("ospf", {})
    vlans = intent["network"].get("vlans", [])
    results = []

    for device, port in [("R1", 5000), ("R2", 5001)]:
        try:
            conn = connect(port)
            conn.enable()

            cmds = [
                "conf t",
                # Remove RIP
                "no router rip",
                # Restore OSPF
                f"router ospf {ospf.get('process_id', 1)}",
            ]

            if device == "R1":
                cmds.append(f" router-id {ospf.get('r1_router_id', '1.1.1.1')}")
                for vlan in vlans:
                    subnet = vlan["subnet"].split("/")[0]
                    cmds.append(f" network {subnet} 0.0.0.255 area 0")
                cmds.append(f" network 10.0.0.0 0.0.0.3 area 0")
            elif device == "R2":
                cmds.append(f" router-id {ospf.get('r2_router_id', '2.2.2.2')}")
                cmds.append(f" network 10.0.0.0 0.0.0.3 area 0")

            cmds.append("end")

            for cmd in cmds:
                conn.send_command_timing(cmd.strip(), delay_factor=2)
            conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
            conn.disconnect()
            print(f"  ✅ {device} restored to OSPF")
            results.append({"device": device, "status": "success"})
        except Exception as e:
            print(f"  ❌ {device}: {e}")
            results.append({"device": device, "status": "error", "error": str(e)})

    intent["network"]["routing_protocol"] = "ospf"
    with open("intent.json", "w") as f:
        json.dump(intent, f, indent=2)

    return results

def generate_ospf_preview(changes):
    """Generate dry-run preview of OSPF changes."""
    lines = ["=== OSPF CONFIGURATION CHANGES (DRY RUN) ===\n"]
    if changes.get("r1_router_id"):
        lines.append(f"R1: router ospf 1\n     router-id {changes['r1_router_id']}")
    if changes.get("r2_router_id"):
        lines.append(f"R2: router ospf 1\n     router-id {changes['r2_router_id']}")
    return "\n".join(lines)

def generate_ripv2_preview():
    """Generate dry-run preview of RIPv2 migration."""
    with open("intent.json") as f:
        intent = json.load(f)
    vlans = intent["network"].get("vlans", [])

    lines = [
        "=== MIGRATION: OSPF → RIPv2 (DRY RUN) ===",
        "",
        "R1 & R2:",
        "  no router ospf 1",
        "  router rip",
        "   version 2",
        "   no auto-summary",
    ]
    for vlan in vlans:
        subnet = vlan["subnet"].split("/")[0]
        lines.append(f"   network {subnet}")
    lines.append("   network 10.0.0.0")
    lines.append("")
    lines.append("⚠️  Network will reconverge (~30 seconds downtime)")
    lines.append("⚠️  RIPv2 converges slower than OSPF")
    lines.append("⚠️  RIPv2 has 15-hop limit")
    return "\n".join(lines)

if __name__ == "__main__":
    print("Routing Engine Test")
    config = get_current_routing_config()
    print("R1 protocols:")
    print(config.get("R1", {}).get("protocols", "")[:200])
