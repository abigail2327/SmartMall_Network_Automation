import json
import ipaddress
import requests
from config import GNS3_API, GNS3_AUTH


def load_intent():
    with open("intent.json") as f:
        return json.load(f)

def get_used_vlans():
    intent = load_intent()
    return [int(v["id"]) for v in intent["network"]["vlans"]]

def get_next_vlan():
    used = get_used_vlans()
    for vlan in range(60, 200):
        if vlan not in used:
            return vlan
    raise Exception("No available VLAN IDs")

def get_next_subnet(vlan_id):
    return f"192.168.{vlan_id}.0/24"

def get_gateway(vlan_id):
    return f"192.168.{vlan_id}.1"

def get_acl_number(vlan_id):
    return vlan_id + 100

def get_project_id():
    with open("topology.json") as f:
        topology = json.load(f)
    r = requests.get(f"{GNS3_API}/projects", auth=GNS3_AUTH)
    for p in r.json():
        if p["name"] == topology["project"]:
            return p["project_id"], topology
    raise Exception("Project not found")

def get_sw1_used_ports(project_id, sw1_id):
    """Get all port numbers currently used on SW1."""
    r = requests.get(f"{GNS3_API}/projects/{project_id}/links", auth=GNS3_AUTH)
    used = set()
    for link in r.json():
        for ep in link.get("nodes", []):
            if ep["node_id"] == sw1_id:
                # Convert adapter + port to flat port number
                flat = ep["adapter_number"] * 4 + ep["port_number"]
                used.add(flat)
                print(f"    SW1 port in use: adapter={ep['adapter_number']} port={ep['port_number']} → flat={flat}")
    return used

def get_sw1_id(project_id):
    r = requests.get(f"{GNS3_API}/projects/{project_id}/nodes", auth=GNS3_AUTH)
    for n in r.json():
        if n["name"] == "SW1":
            return n["node_id"], n
    raise Exception("SW1 not found")

def get_next_sw1_port(target_node_id=None):
    """Find next available port on target node (defaults to SW1).
    For SW1, skips ports 0-5 (reserved for original topology links).
    For any other node (e.g. tenant switch), starts from port 0.
    Returns (flat_port, adapter, port, iface_name).
    """
    project_id, topology = get_project_id()
    if target_node_id is None:
        target_node_id, _ = get_sw1_id(project_id)
        start_flat = 6  # skip reserved SW1 ports
    else:
        start_flat = 0  # fresh switch, start from beginning

    used = get_sw1_used_ports(project_id, target_node_id)
    print(f"  Used ports (flat) on node: {sorted(used)}")

    for flat in range(start_flat, 64):
        if flat not in used:
            adapter = flat // 4
            port = flat % 4
            iface = f"Ethernet{adapter}/{port}"
            print(f"  Next available port: {iface} (flat={flat})")
            return flat, adapter, port, iface

    raise Exception("No available ports (all 64 used)")

def get_next_switch_name():
    with open("topology.json") as f:
        topology = json.load(f)
    existing = [n["name"] for n in topology["nodes"] if n["name"].startswith("SW")]
    for i in range(2, 20):
        name = f"SW{i}"
        if name not in existing:
            return name
    return "SW2"

def get_next_router_name():
    with open("topology.json") as f:
        topology = json.load(f)
    existing = [n["name"] for n in topology["nodes"] if n["name"].startswith("R")]
    for i in range(3, 20):
        name = f"R{i}"
        if name not in existing:
            return name
    return "R3"

def get_tenant_type_defaults(tenant_type):
    defaults = {
        "retail":     {"num_hosts": 2,  "access": ["internet","payment"], "qos": "medium", "needs_switch": False, "needs_router": False},
        "restaurant": {"num_hosts": 3,  "access": ["internet","payment"], "qos": "medium", "needs_switch": False, "needs_router": False},
        "bank":       {"num_hosts": 3,  "access": ["payment"],            "qos": "high",   "needs_switch": False, "needs_router": False},
        "food_court": {"num_hosts": 8,  "access": ["internet","payment"], "qos": "medium", "needs_switch": True,  "needs_router": False},
        "anchor":     {"num_hosts": 10, "access": ["all"],                "qos": "high",   "needs_switch": True,  "needs_router": True},
        "popup":      {"num_hosts": 1,  "access": ["internet"],           "qos": "low",    "needs_switch": False, "needs_router": False, "duration_days": 7},
    }
    return defaults.get(tenant_type, {
        "num_hosts": 1, "access": ["internet"], "qos": "medium",
        "needs_switch": False, "needs_router": False
    })

def check_conflicts(vlan_id, subnet):
    errors = []
    used_vlans = get_used_vlans()
    if int(vlan_id) in used_vlans:
        errors.append(f"VLAN {vlan_id} already in use")
    try:
        new_net = ipaddress.IPv4Network(subnet, strict=False)
        intent = load_intent()
        for v in intent["network"]["vlans"]:
            existing_net = ipaddress.IPv4Network(v["subnet"], strict=False)
            if new_net.overlaps(existing_net):
                errors.append(f"Subnet {subnet} overlaps with VLAN {v['id']} ({v['subnet']})")
    except ValueError as e:
        errors.append(f"Invalid subnet: {e}")
    return errors

def build_tenant_config(parsed):
    """Build full tenant config with auto-filled fields."""
    tenant_type = parsed.get("tenant_type", "retail")
    defaults = get_tenant_type_defaults(tenant_type)

    vlan_id = parsed.get("vlan_id") or get_next_vlan()
    subnet  = parsed.get("subnet")  or get_next_subnet(vlan_id)
    gateway = parsed.get("gateway") or get_gateway(vlan_id)
    acl_num = get_acl_number(int(vlan_id))

    config = {
        "name":         parsed.get("tenant_name") or parsed.get("name") or "NewTenant",
        "tenant_type":  tenant_type,
        "vlan_id":      int(vlan_id),
        "subnet":       subnet,
        "gateway":      gateway,
        "acl_number":   acl_num,
        "num_hosts":    parsed.get("num_hosts")    or defaults["num_hosts"],
        "access":       parsed.get("access")       or defaults["access"],
        "qos":          parsed.get("qos")          or defaults["qos"],
        "needs_switch": parsed.get("needs_switch") or defaults.get("needs_switch", False),
        "needs_router": parsed.get("needs_router") or defaults.get("needs_router", False),
        "duration_days":parsed.get("duration_days") or defaults.get("duration_days", None),
    }

    if config["needs_switch"]:
        config["switch_name"] = get_next_switch_name()
    if config["needs_router"]:
        config["router_name"] = get_next_router_name()

    conflicts = check_conflicts(config["vlan_id"], config["subnet"])
    config["conflicts"] = conflicts
    config["safe_to_deploy"] = len(conflicts) == 0

    return config

if __name__ == "__main__":
    print("Decision Engine Test")
    print(f"Next VLAN: {get_next_vlan()}")
    vlan = get_next_vlan()
    print(f"Next subnet: {get_next_subnet(vlan)}")
    flat, adapter, port, iface = get_next_sw1_port()
    print(f"Next SW1 port: {iface} (adapter={adapter}, port={port}, flat={flat})")
