import json
import time
import requests
import os
from config import GNS3_HOST, GNS3_API, GNS3_AUTH, CISCO_SECRET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TENANTS_FILE = os.path.join(BASE_DIR, "tenants.json")
INTENT_FILE  = os.path.join(BASE_DIR, "intent.json")
from netmiko import ConnectHandler
from host_manager import (
    load_topology, send_docker_command,
    set_host_ip, get_node, ping_from_host
)
from decision_engine import get_next_sw1_port, build_tenant_config, get_project_id
from discover import discover


# ── GNS3 REST API HELPERS ────────────────────────────────

def get_node_id(project_id, name):
    r = requests.get(f"{GNS3_API}/projects/{project_id}/nodes", auth=GNS3_AUTH)
    for n in r.json():
        if n["name"] == name:
            return n["node_id"], n
    return None, None

def add_networkhost(project_id, name, x=0, y=0):
    """Add a NetworkHost (nicolaka/netshoot Docker) node."""
    data = {
        "name": name,
        "node_type": "docker",
        "compute_id": "local",
        "properties": {
            "image": "nicolaka/netshoot",
            "adapters": 1,
            "start_command": "",
            "environment": "",
            "console_type": "telnet"
        },
        "x": x, "y": y
    }
    r = requests.post(f"{GNS3_API}/projects/{project_id}/nodes",
                      json=data, auth=GNS3_AUTH)
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create {name}: {r.text}")
    node = r.json()
    print(f"  ✅ Created NetworkHost '{name}'")
    return node["node_id"], node.get("console")

def add_c7200_router(project_id, name, x=0, y=0):
    """Add a c7200 router — uses existing template."""
    # Find c7200 template
    r = requests.get(f"{GNS3_API}/templates", auth=GNS3_AUTH)
    template_id = None
    for t in r.json():
        if "7200" in t.get("name","") or "7200" in t.get("template_id",""):
            template_id = t["template_id"]
            break

    if template_id:
        data = {"x": x, "y": y, "name": name, "compute_id": "local"}
        r = requests.post(
            f"{GNS3_API}/projects/{project_id}/templates/{template_id}",
            json=data, auth=GNS3_AUTH
        )
    else:
        # Fallback — create dynamips node directly
        data = {
            "name": name,
            "node_type": "dynamips",
            "compute_id": "local",
            "properties": {"platform": "c7200"},
            "x": x, "y": y
        }
        r = requests.post(f"{GNS3_API}/projects/{project_id}/nodes",
                          json=data, auth=GNS3_AUTH)

    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create router {name}: {r.text}")
    node = r.json()
    print(f"  ✅ Created c7200 router '{name}'")
    return node["node_id"], node.get("console")

def add_iou_switch(project_id, name, x=0, y=0):
    """Add an IOU L2 switch — uses existing template."""
    r = requests.get(f"{GNS3_API}/templates", auth=GNS3_AUTH)
    template_id = None
    for t in r.json():
        if "IOU" in t.get("name","") and "L2" in t.get("name",""):
            template_id = t["template_id"]
            break

    if template_id:
        data = {"x": x, "y": y, "name": name, "compute_id": "local"}
        r = requests.post(
            f"{GNS3_API}/projects/{project_id}/templates/{template_id}",
            json=data, auth=GNS3_AUTH
        )
        if r.status_code not in [200, 201]:
            raise Exception(f"Failed to create switch {name}: {r.text}")
        node = r.json()
        print(f"  ✅ Created IOU L2 switch '{name}'")
        return node["node_id"], node.get("console")
    else:
        raise Exception("IOU L2 template not found in GNS3")

def create_link(project_id, node_a_id, adapter_a, port_a, node_b_id, adapter_b, port_b):
    """Create a link between two nodes."""
    link_data = {
        "nodes": [
            {"node_id": node_a_id, "adapter_number": adapter_a, "port_number": port_a},
            {"node_id": node_b_id, "adapter_number": adapter_b, "port_number": port_b}
        ]
    }
    r = requests.post(f"{GNS3_API}/projects/{project_id}/links",
                      json=link_data, auth=GNS3_AUTH)
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create link: {r.text}")
    return r.json()

def start_node(project_id, node_id):
    requests.post(f"{GNS3_API}/projects/{project_id}/nodes/{node_id}/start",
                  auth=GNS3_AUTH)

def stop_node(project_id, node_id):
    requests.post(f"{GNS3_API}/projects/{project_id}/nodes/{node_id}/stop",
                  auth=GNS3_AUTH)

def delete_node(project_id, node_id):
    requests.delete(f"{GNS3_API}/projects/{project_id}/nodes/{node_id}",
                    auth=GNS3_AUTH)

# ── ROUTER CONFIG HELPERS ────────────────────────────────

def router_connect(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST, port=port,
        username="", password="", secret=CISCO_SECRET,
        timeout=60
    )

def subnet_to_wildcard(subnet):
    parts = subnet.split("/")
    base   = parts[0]
    prefix = int(parts[1]) if len(parts) > 1 else 24
    mask_bits = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    wild_bits = (~mask_bits) & 0xFFFFFFFF
    wild_parts = [str((wild_bits >> (i*8)) & 0xFF) for i in range(3,-1,-1)]
    return base, ".".join(wild_parts)

def build_acl_rules(config):
    base, wildcard = subnet_to_wildcard(config["subnet"])
    rules  = []
    access = config["access"]
    if "all" in access:
        rules.append("permit ip any any")
    else:
        if "payment" in access:
            rules.append(f"permit ip {base} {wildcard} 192.168.50.0 0.0.0.255")
        if "admin" in access:
            rules.append(f"permit ip {base} {wildcard} 192.168.10.0 0.0.0.255")
        if "cctv" in access:
            rules.append(f"permit ip {base} {wildcard} 192.168.40.0 0.0.0.255")
        if "internet" in access or not rules:
            rules.append(f"permit ip {base} {wildcard} any")
        rules.append("deny ip any any")
    return rules, base, wildcard

def configure_r1(config, topology):
    """Add subinterface + ACL + OSPF on R1."""
    r1_port = get_node(topology, "R1")["console_port"]
    vlan_id = config["vlan_id"]
    gateway = config["gateway"]
    acl_num = config["acl_number"]
    rules, base, wildcard = build_acl_rules(config)
    acl_lines = "\n".join(f" {r}" for r in rules)

    cmds = f"""conf t
interface FastEthernet0/0.{vlan_id}
 encapsulation dot1Q {vlan_id}
 ip address {gateway} 255.255.255.0
 no shutdown
ip access-list extended {acl_num}
{acl_lines}
interface FastEthernet0/0.{vlan_id}
 ip access-group {acl_num} in
router ospf 1
 network {base} {wildcard} area 0
end"""

    print(f"  Configuring R1 — f0/0.{vlan_id}, ACL {acl_num}...")
    conn = router_connect(r1_port)
    conn.enable()
    for cmd in cmds.splitlines():
        cmd = cmd.strip()
        if cmd:
            conn.send_command_timing(cmd, delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ R1 configured")
    return cmds

def configure_sw1_vlan_and_port(config, sw1_iface, topology):
    """Add VLAN + set access port on SW1."""
    sw1_port = get_node(topology, "SW1")["console_port"]
    vlan_id  = config["vlan_id"]
    name     = config["name"]

    cmds = f"""conf t
vlan {vlan_id}
 name {name}
interface {sw1_iface}
 switchport mode access
 switchport access vlan {vlan_id}
 no shutdown
end"""

    conn = router_connect(sw1_port)
    conn.enable()
    for cmd in cmds.splitlines():
        cmd = cmd.strip()
        if cmd:
            conn.send_command_timing(cmd, delay_factor=2)
    conn.send_command_timing("write memory", delay_factor=4)
    conn.disconnect()
    print(f"  ✅ SW1: VLAN {vlan_id} on {sw1_iface}")
    return cmds

# ── MAIN ONBOARDING ──────────────────────────────────────

def onboard_tenant(config):
    # Normalize name — remove spaces, capitalize words
    name      = config["name"].replace(" ", "").strip()
    config["name"] = name  # Update config with normalized name
    vlan_id   = config["vlan_id"]
    num_hosts = config["num_hosts"]
    gateway   = config["gateway"]

    print(f"\n{'='*50}")
    print(f"ONBOARDING: {name} | VLAN {vlan_id} | {num_hosts} host(s)")
    print(f"{'='*50}")

    project_id, topology_raw = get_project_id()
    sw1_id, sw1_node = get_node_id(project_id, "SW1")
    sw1_x = sw1_node.get("x", 0) if sw1_node else 0
    sw1_y = sw1_node.get("y", 0) if sw1_node else 0

    created_nodes   = []
    host_iface_map  = []  # [(sw1_iface, host_name)]

    # ── STEP 1: Optional tenant switch ──────────────────
    connect_target_id = sw1_id
    if config.get("needs_switch"):
        sw_name = config.get("switch_name", "SW2")
        print(f"\n[1/7] Adding switch {sw_name}...")
        sw_id, _ = add_iou_switch(project_id, sw_name,
                                   x=sw1_x+200, y=sw1_y)
        created_nodes.append(sw_id)
        # Connect new switch to SW1
        flat, adp, prt, iface = get_next_sw1_port()
        create_link(project_id, sw1_id, adp, prt, sw_id, 0, 0)
        print(f"  ✅ {sw_name} linked to SW1 {iface}")
        time.sleep(2)
        start_node(project_id, sw_id)
        connect_target_id = sw_id
    else:
        print(f"\n[1/7] No switch needed")

    # ── STEP 2: Optional tenant router ──────────────────
    if config.get("needs_router"):
        r_name = config.get("router_name", "R3")
        print(f"\n[2/7] Adding router {r_name}...")
        r_id, _ = add_c7200_router(project_id, r_name,
                                    x=sw1_x+400, y=sw1_y-100)
        created_nodes.append(r_id)
        time.sleep(2)
        start_node(project_id, r_id)
        print(f"  ✅ {r_name} added (connect manually for routing)")
    else:
        print(f"\n[2/7] No router needed")

    # ── STEP 3: Add NetworkHost nodes ───────────────────
    print(f"\n[3/7] Adding {num_hosts} NetworkHost node(s)...")
    host_nodes = []
    for i in range(num_hosts):
        host_name = name if num_hosts == 1 else f"{name}_{i+1}"
        x_pos = sw1_x + (i - num_hosts//2) * 110
        y_pos = sw1_y + 120

        node_id, console = add_networkhost(project_id, host_name,
                                            x=x_pos, y=y_pos)
        created_nodes.append(node_id)

        # Get next available port on connect_target (SW1 or tenant switch)
        # Pass connect_target_id so port tracking scans the right switch
        target_for_scan = None if connect_target_id == sw1_id else connect_target_id
        flat, adp, prt, iface = get_next_sw1_port(target_for_scan)

        create_link(project_id,
                    node_id, 0, 0,
                    connect_target_id, adp, prt)
        print(f"  ✅ {host_name} → {iface}")
        host_iface_map.append((iface, host_name))
        host_nodes.append({"name": host_name, "node_id": node_id})
        time.sleep(1)

    # Start all hosts
    print(f"  Starting hosts...")
    for h in host_nodes:
        start_node(project_id, h["node_id"])
    time.sleep(8)  # Wait for Docker to boot

    # ── STEP 4: Refresh topology ─────────────────────────
    print(f"\n[4/7] Refreshing topology...")
    discover()
    topology = load_topology()

    # ── STEP 5: Configure SW1 ────────────────────────────
    print(f"\n[5/7] Configuring SW1...")
    sw1_conn_port = get_node(topology, "SW1")["console_port"]
    conn = router_connect(sw1_conn_port)
    conn.enable()
    conn.send_command_timing("conf t", delay_factor=1)
    conn.send_command_timing(f"vlan {vlan_id}", delay_factor=1)
    conn.send_command_timing(f" name {name}", delay_factor=1)
    for iface, hname in host_iface_map:
        conn.send_command_timing(f"interface {iface}", delay_factor=1)
        conn.send_command_timing(f" switchport mode access", delay_factor=1)
        conn.send_command_timing(f" switchport access vlan {vlan_id}", delay_factor=1)
        conn.send_command_timing(f" no shutdown", delay_factor=1)
    conn.send_command_timing("end", delay_factor=1)
    conn.send_command_timing("write memory", delay_factor=4)
    conn.disconnect()
    print(f"  ✅ SW1 VLAN {vlan_id} on {len(host_iface_map)} port(s)")

    # ── STEP 6: Configure R1 ─────────────────────────────
    print(f"\n[6/7] Configuring R1...")
    r1_config = configure_r1(config, topology)
    time.sleep(3)

    # ── STEP 7: Set IPs on hosts ─────────────────────────
    print(f"\n[7/7] Setting IPs on hosts...")
    base_ip  = ".".join(gateway.split(".")[:3])
    host_ips = []
    for i, h in enumerate(host_nodes):
        host_ip = f"{base_ip}.{10+i}/24"
        time.sleep(4)
        result = set_host_ip(h["name"], host_ip, gateway, topology)
        host_ips.append({"host": h["name"], "ip": host_ip})

    # ── Update intent.json ───────────────────────────────
    with open(INTENT_FILE) as f:
        intent = json.load(f)
    intent["network"]["vlans"].append({
        "id": str(vlan_id), "name": name,
        "subnet": config["subnet"], "gateway": gateway
    })
    with open(INTENT_FILE, "w") as f:
        json.dump(intent, f, indent=2)

    # Save tenant record
    print(f'  Saving tenant record for {name}...')
    try:
        save_tenant_record(config, host_nodes, host_ips)
        print(f'  ✅ Tenant record saved to tenants.json')
    except Exception as e:
        print(f'  ❌ Failed to save tenant record: {e}')
        import traceback
        traceback.print_exc()

    # Schedule offboard if timed
    if config.get("duration_days"):
        print(f"  ⏰ Auto-offboard in {config['duration_days']} days (scheduler)")

    print(f"\n✅ '{name}' ONBOARDED!")
    print(f"   VLAN {vlan_id} — {config['subnet']}")
    print(f"   {num_hosts} host(s) added to GNS3")
    return {
        "status": "success", "tenant": name,
        "vlan_id": vlan_id, "subnet": config["subnet"],
        "hosts": host_ips
    }

# ── OFFBOARDING ──────────────────────────────────────────

def offboard_tenant(tenant_name):
    print(f"\n{'='*50}")
    print(f"OFFBOARDING: {tenant_name}")
    print(f"{'='*50}")

    record = load_tenant_record(tenant_name)
    if not record:
        return {"status": "error", "message": f"Tenant '{tenant_name}' not found"}

    config  = record["config"]
    vlan_id = config["vlan_id"]
    acl_num = config["acl_number"]
    project_id, _ = get_project_id()
    topology = load_topology()

    # Remove R1 config
    print("[1/4] Removing R1 config...")
    r1_port = get_node(topology, "R1")["console_port"]
    base, wildcard = subnet_to_wildcard(config["subnet"])
    conn = router_connect(r1_port)
    conn.enable()
    for cmd in [
        "conf t",
        f"no interface FastEthernet0/0.{vlan_id}",
        f"no ip access-list extended {acl_num}",
        "router ospf 1",
        f"no network {base} {wildcard} area 0",
        "end"
    ]:
        conn.send_command_timing(cmd, delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ R1: f0/0.{vlan_id} and ACL {acl_num} removed")

    # Remove SW1 VLAN
    print("[2/4] Removing SW1 VLAN...")
    sw1_port = get_node(topology, "SW1")["console_port"]
    conn = router_connect(sw1_port)
    conn.enable()
    conn.send_command_timing("conf t", delay_factor=1)
    conn.send_command_timing(f"no vlan {vlan_id}", delay_factor=2)
    conn.send_command_timing("end", delay_factor=1)
    conn.send_command_timing("write memory", delay_factor=4)
    conn.disconnect()
    print(f"  ✅ VLAN {vlan_id} removed from SW1")

    # Delete GNS3 nodes
    print("[3/4] Removing GNS3 nodes...")
    for host in record.get("hosts", []):
        node_id, _ = get_node_id(project_id, host["host"])
        if node_id:
            stop_node(project_id, node_id)
            time.sleep(1)
            delete_node(project_id, node_id)
            print(f"  ✅ {host['host']} removed")

    if config.get("needs_switch") and config.get("switch_name"):
        sw_name = config["switch_name"]
        sw_node_id, _ = get_node_id(project_id, sw_name)
        if sw_node_id:
            stop_node(project_id, sw_node_id)
            time.sleep(1)
            delete_node(project_id, sw_node_id)
            print(f"  ✅ {sw_name} removed")

    # Update intent.json
    print("[4/4] Updating project files...")
    with open(INTENT_FILE) as f:
        intent = json.load(f)
    intent["network"]["vlans"] = [
        v for v in intent["network"]["vlans"]
        if str(v["id"]) != str(vlan_id)
    ]
    with open(INTENT_FILE, "w") as f:
        json.dump(intent, f, indent=2)

    delete_tenant_record(tenant_name)
    discover()

    print(f"\n✅ '{tenant_name}' OFFBOARDED!")
    return {"status": "success", "tenant": tenant_name}

# ── TENANT RECORDS ───────────────────────────────────────

def save_tenant_record(config, host_nodes, host_ips):
    import datetime
    records = load_all_tenant_records()
    records[config["name"]] = {
        "config": config,
        "hosts": host_ips,
        "host_nodes": host_nodes,
        "onboarded_at": datetime.datetime.now().isoformat()
    }
    with open(TENANTS_FILE, "w") as f:
        json.dump(records, f, indent=2)

def load_tenant_record(name):
    return load_all_tenant_records().get(name)

def delete_tenant_record(name):
    records = load_all_tenant_records()
    records.pop(name, None)
    with open(TENANTS_FILE, "w") as f:
        json.dump(records, f, indent=2)

def load_all_tenant_records():
    try:
        with open(TENANTS_FILE) as f:
            return json.load(f)
    except:
        return {}

# ── PREVIEW ──────────────────────────────────────────────

def generate_preview(config):
    rules, base, wildcard = build_acl_rules(config)
    acl_lines = "\n".join(f"  {r}" for r in rules)
    vlan_id = config["vlan_id"]
    name    = config["name"]
    acl_num = config["acl_number"]
    gateway = config["gateway"]
    num_hosts = config["num_hosts"]

    preview = f"""=== TENANT ONBOARDING PREVIEW ===
Tenant:   {name} ({config['tenant_type']})
VLAN:     {vlan_id}
Subnet:   {config['subnet']}
Gateway:  {gateway}
Hosts:    {num_hosts} × NetworkHost (nicolaka/netshoot)
Access:   {', '.join(config['access'])}
QoS:      {config['qos']} priority
"""
    if config.get("needs_switch"):
        preview += f"Switch:   {config.get('switch_name')} (IOU L2) will be added\n"
    if config.get("needs_router"):
        preview += f"Router:   {config.get('router_name')} (c7200) will be added\n"
    if config.get("duration_days"):
        preview += f"Duration: {config['duration_days']} days (auto-offboard)\n"

    preview += f"""
=== R1 CONFIG ===
conf t
interface FastEthernet0/0.{vlan_id}
 encapsulation dot1Q {vlan_id}
 ip address {gateway} 255.255.255.0
 no shutdown
ip access-list extended {acl_num}
{acl_lines}
interface FastEthernet0/0.{vlan_id}
 ip access-group {acl_num} in
router ospf 1
 network {base} {wildcard} area 0
end

=== SW1 CONFIG ===
conf t
vlan {vlan_id}
 name {name}
(access ports auto-assigned per host)
end"""
    return preview
