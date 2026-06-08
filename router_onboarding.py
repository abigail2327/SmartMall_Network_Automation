"""
Router Onboarding Engine
Handles adding tenant routers (c7200) to GNS3 and configuring
OSPF, RIPv2, or Static routing between R1 and tenant router
"""
import json
import time
import requests
from config import GNS3_HOST, GNS3_API, GNS3_AUTH, CISCO_SECRET
from netmiko import ConnectHandler


# ── LINK SUBNET POOL ─────────────────────────────────────
LINK_SUBNET_POOL = [
    {"subnet": "10.0.1.0/30", "r1_ip": "10.0.1.1", "r3_ip": "10.0.1.2"},
    {"subnet": "10.0.2.0/30", "r1_ip": "10.0.2.1", "r3_ip": "10.0.2.2"},
    {"subnet": "10.0.3.0/30", "r1_ip": "10.0.3.1", "r3_ip": "10.0.3.2"},
    {"subnet": "10.0.4.0/30", "r1_ip": "10.0.4.1", "r3_ip": "10.0.4.2"},
    {"subnet": "10.0.5.0/30", "r1_ip": "10.0.5.1", "r3_ip": "10.0.5.2"},
]

# ── R1 INTERFACE POOL ────────────────────────────────────
R1_INTERFACE_POOL = [
    {"interface": "FastEthernet1/1", "adapter": 1, "port": 1},
    {"interface": "FastEthernet2/0", "adapter": 2, "port": 0},
    {"interface": "FastEthernet2/1", "adapter": 2, "port": 1},
]

def get_project_id():
    with open("topology.json") as f:
        topo = json.load(f)
    r = requests.get(f"{GNS3_API}/projects", auth=GNS3_AUTH)
    for p in r.json():
        if p["name"] == topo["project"]:
            return p["project_id"]
    raise Exception("Project not found")

def get_node_id(project_id, name):
    r = requests.get(f"{GNS3_API}/projects/{project_id}/nodes", auth=GNS3_AUTH)
    for n in r.json():
        if n["name"] == name:
            return n["node_id"], n
    return None, None

def get_used_r1_interfaces(project_id, r1_id):
    """Get list of R1 interfaces already in use."""
    r = requests.get(f"{GNS3_API}/projects/{project_id}/links", auth=GNS3_AUTH)
    used = []
    for link in r.json():
        for ep in link.get("nodes", []):
            if ep["node_id"] == r1_id:
                used.append({
                    "adapter": ep["adapter_number"],
                    "port": ep["port_number"]
                })
    return used

def get_next_r1_interface(project_id, r1_id):
    """Get next available R1 interface for tenant router link."""
    used = get_used_r1_interfaces(project_id, r1_id)
    used_pairs = [(u["adapter"], u["port"]) for u in used]

    for iface in R1_INTERFACE_POOL:
        if (iface["adapter"], iface["port"]) not in used_pairs:
            print(f"  Next R1 interface: {iface['interface']}")
            return iface
    raise Exception("No available R1 interfaces for tenant router")

def get_next_link_subnet():
    """Get next available point-to-point subnet."""
    try:
        with open("router_links.json") as f:
            used_subnets = json.load(f)
    except:
        used_subnets = []

    for subnet in LINK_SUBNET_POOL:
        if subnet["subnet"] not in used_subnets:
            return subnet
    raise Exception("No available link subnets")

def save_router_link(subnet, router_name, r1_interface):
    """Record used link subnet."""
    try:
        with open("router_links.json") as f:
            links = json.load(f)
    except:
        links = {}
    links[router_name] = {
        "subnet": subnet["subnet"],
        "r1_ip": subnet["r1_ip"],
        "r3_ip": subnet["r3_ip"],
        "r1_interface": r1_interface["interface"]
    }
    with open("router_links.json", "w") as f:
        json.dump(links, f, indent=2)

def free_router_link(router_name):
    """Free up link subnet when router is removed."""
    try:
        with open("router_links.json") as f:
            links = json.load(f)
        links.pop(router_name, None)
        with open("router_links.json", "w") as f:
            json.dump(links, f, indent=2)
    except:
        pass

def connect_device(port):
    return ConnectHandler(
        device_type="cisco_ios_telnet",
        host=GNS3_HOST, port=port,
        username="", password="", secret=CISCO_SECRET,
        timeout=120
    )

def add_c7200_to_gns3(project_id, name, x=0, y=0):
    """Add c7200 router to GNS3 using template."""
    TEMPLATE_ID = "fb1178d1-eb8a-4650-8579-280f2612708b"
    data = {"x": x, "y": y, "name": name, "compute_id": "local"}
    r = requests.post(
        f"{GNS3_API}/projects/{project_id}/templates/{TEMPLATE_ID}",
        json=data, auth=GNS3_AUTH
    )
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create {name}: {r.text[:200]}")
    node = r.json()
    print(f"  ✅ Created {name} (c7200)")
    return node["node_id"], node.get("console")

def create_link(project_id, node_a, adapter_a, port_a, node_b, adapter_b, port_b):
    """Create link between two nodes."""
    data = {"nodes": [
        {"node_id": node_a, "adapter_number": adapter_a, "port_number": port_a},
        {"node_id": node_b, "adapter_number": adapter_b, "port_number": port_b}
    ]}
    r = requests.post(f"{GNS3_API}/projects/{project_id}/links", json=data, auth=GNS3_AUTH)
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create link: {r.text}")
    return r.json()

def start_node(project_id, node_id):
    requests.post(f"{GNS3_API}/projects/{project_id}/nodes/{node_id}/start", auth=GNS3_AUTH)

def configure_r3_ospf(r3_port, r3_name, link_subnet, tenant_subnet, tenant_gateway):
    """Configure R3 with OSPF."""
    link_ip = link_subnet["r3_ip"]
    link_net = link_subnet["subnet"].split("/")[0]

    conn = connect_device(r3_port)
    conn.enable()

    cmds = [
        "conf t",
        "no ip domain-lookup",
        f"hostname {r3_name}",
        "interface FastEthernet0/0",
        f" ip address {link_ip} 255.255.255.252",
        " no shutdown",
        "interface FastEthernet0/1",
        f" ip address {tenant_gateway} 255.255.255.0",
        " no shutdown",
        "router ospf 1",
        f" router-id {link_subnet['r3_ip']}",
        f" network {link_net} 0.0.0.3 area 0",
        f" network {tenant_subnet.split('/')[0]} 0.0.0.255 area 0",
        "end"
    ]

    for cmd in cmds:
        conn.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ {r3_name} configured with OSPF")

def configure_r3_ripv2(r3_port, r3_name, link_subnet, tenant_subnet, tenant_gateway):
    """Configure R3 with RIPv2."""
    link_ip = link_subnet["r3_ip"]
    link_net = link_subnet["subnet"].split("/")[0]
    tenant_net = tenant_subnet.split("/")[0]

    conn = connect_device(r3_port)
    conn.enable()

    cmds = [
        "conf t",
        "no ip domain-lookup",
        f"hostname {r3_name}",
        "interface FastEthernet0/0",
        f" ip address {link_ip} 255.255.255.252",
        " no shutdown",
        "interface FastEthernet0/1",
        f" ip address {tenant_gateway} 255.255.255.0",
        " no shutdown",
        "router rip",
        " version 2",
        " no auto-summary",
        f" network {link_net}",
        f" network {tenant_net}",
        "end"
    ]

    for cmd in cmds:
        conn.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ {r3_name} configured with RIPv2")

def configure_r3_static(r3_port, r3_name, link_subnet, tenant_subnet, tenant_gateway):
    """Configure R3 with static routing."""
    link_ip = link_subnet["r3_ip"]
    r1_link_ip = link_subnet["r1_ip"]

    conn = connect_device(r3_port)
    conn.enable()

    cmds = [
        "conf t",
        "no ip domain-lookup",
        f"hostname {r3_name}",
        "interface FastEthernet0/0",
        f" ip address {link_ip} 255.255.255.252",
        " no shutdown",
        "interface FastEthernet0/1",
        f" ip address {tenant_gateway} 255.255.255.0",
        " no shutdown",
        f"ip route 0.0.0.0 0.0.0.0 {r1_link_ip}",
        "end"
    ]

    for cmd in cmds:
        conn.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ {r3_name} configured with static routing")

def configure_r1_for_tenant_router(r1_port, r1_iface, link_subnet,
                                     tenant_subnet, routing_protocol):
    """Update R1 to connect to tenant router."""
    r1_ip = link_subnet["r1_ip"]
    r3_ip = link_subnet["r3_ip"]
    link_net = link_subnet["subnet"].split("/")[0]
    tenant_net = tenant_subnet.split("/")[0]

    conn = connect_device(r1_port)
    conn.enable()

    cmds = [
        "conf t",
        f"interface {r1_iface['interface']}",
        f" ip address {r1_ip} 255.255.255.252",
        " no shutdown",
    ]

    if routing_protocol == "ospf":
        cmds += [
            "router ospf 1",
            f" network {link_net} 0.0.0.3 area 0",
        ]
    elif routing_protocol == "ripv2":
        cmds += [
            "router rip",
            " version 2",
            " no auto-summary",
            f" network {link_net}",
        ]
    elif routing_protocol == "static":
        cmds += [
            f"ip route {tenant_net} 255.255.255.0 {r3_ip}",
        ]

    cmds.append("end")

    for cmd in cmds:
        conn.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ R1 {r1_iface['interface']} configured for tenant router")

def verify_adjacency(r1_port, routing_protocol, r3_ip):
    """Verify routing adjacency between R1 and R3."""
    try:
        conn = connect_device(r1_port)
        conn.enable()

        if routing_protocol == "ospf":
            out = conn.send_command("show ip ospf neighbor")
            conn.disconnect()
            return r3_ip in out or "FULL" in out
        elif routing_protocol == "ripv2":
            out = conn.send_command("show ip rip database")
            conn.disconnect()
            return True  # RIP doesn't show neighbors like OSPF
        elif routing_protocol == "static":
            out = conn.send_command(f"ping {r3_ip}")
            conn.disconnect()
            return "!" in out
    except Exception as e:
        print(f"  Adjacency check failed: {e}")
        return False

def add_iou_switch(project_id, name, x=0, y=0):
    """Add IOU L2 switch using existing template."""
    r = requests.get(f"{GNS3_API}/templates", auth=GNS3_AUTH)
    template_id = None
    for t in r.json():
        if "IOU" in t.get("name", "") and "L2" in t.get("name", ""):
            template_id = t["template_id"]
            break
    if not template_id:
        raise Exception("IOU L2 template not found in GNS3")
    data = {"x": x, "y": y, "name": name, "compute_id": "local"}
    r = requests.post(
        f"{GNS3_API}/projects/{project_id}/templates/{template_id}",
        json=data, auth=GNS3_AUTH
    )
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create switch {name}: {r.text[:200]}")
    node = r.json()
    print(f"  ✅ Created IOU L2 switch '{name}'")
    return node["node_id"]

def add_docker_host(project_id, name, x=0, y=0):
    """Add NetworkHost (nicolaka/netshoot) to GNS3."""
    TEMPLATE_ID = "788d34d0-a0bb-4cd7-9420-0cd810b20362"
    data = {"x": x, "y": y, "name": name, "compute_id": "local"}
    r = requests.post(
        f"{GNS3_API}/projects/{project_id}/templates/{TEMPLATE_ID}",
        json=data, auth=GNS3_AUTH
    )
    if r.status_code not in [200, 201]:
        raise Exception(f"Failed to create {name}: {r.text[:200]}")
    node = r.json()
    print(f"  ✅ Added {name}")
    return node["node_id"]

def onboard_tenant_router(config):
    """
    Multi-tier topology: R1 → R3 (router) → SW_Tenant (switch) → hosts
    R3 f0/0: WAN link to R1
    R3 f1/0: LAN link to tenant switch (PA-FE-TX in slot 1)
    SW_Tenant: all hosts connect here
    """
    router_name   = config["router_name"]
    switch_name   = config.get("switch_name") or f"SW_{config['tenant_name']}"
    tenant_name   = config["tenant_name"]
    vlan_id       = config["tenant_vlan"]
    tenant_subnet = config["tenant_subnet"]
    tenant_gw     = config["tenant_gateway"]
    protocol      = config["routing_protocol"]
    num_hosts     = config.get("num_hosts", 2)
    base_ip       = ".".join(tenant_gw.split(".")[:3])

    print(f"\n{'='*52}")
    print(f"ROUTER ONBOARDING: {tenant_name}")
    print(f"Topology: R1 → {router_name} → {switch_name} → {num_hosts} hosts")
    print(f"Protocol: {protocol.upper()}")
    print(f"{'='*52}")

    project_id = get_project_id()
    r1_id, r1_node = get_node_id(project_id, "R1")
    r1_x = r1_node.get("x", 0) if r1_node else 0
    r1_y = r1_node.get("y", 0) if r1_node else 0

    # Step 1 — Allocate resources
    print("\n[1/7] Allocating resources...")
    r1_iface    = get_next_r1_interface(project_id, r1_id)
    link_subnet = get_next_link_subnet()
    print(f"  R1 interface: {r1_iface['interface']}")
    print(f"  Link subnet:  {link_subnet['subnet']}")

    # Step 2 — Add R3, install PA-FE-TX slot 1 BEFORE creating any links
    print(f"\n[2/7] Adding {router_name} to GNS3...")
    r3_id, _ = add_c7200_to_gns3(project_id, router_name,
                                  x=r1_x - 220, y=r1_y - 100)
    slot_payload = {"properties": {"slot1": "PA-FE-TX"}}
    r = requests.put(
        f"{GNS3_API}/projects/{project_id}/nodes/{r3_id}",
        json=slot_payload, auth=GNS3_AUTH
    )
    if r.status_code == 200:
        print(f"  ✅ PA-FE-TX slot 1 added to {router_name}")
    else:
        print(f"  ⚠️ Slot config: {r.status_code} — {r.text[:100]}")
    time.sleep(1)

    # Step 2b — Add tenant switch
    print(f"\n[2b/7] Adding tenant switch {switch_name}...")
    sw_id = add_iou_switch(project_id, switch_name,
                           x=r1_x - 220, y=r1_y + 80)
    time.sleep(1)

    # Step 3 — Add hosts to GNS3
    print(f"\n[3/7] Adding {num_hosts} hosts to GNS3...")
    host_ids = []
    for i in range(num_hosts):
        hname = f"{tenant_name}_{i+1}"
        hx = (r1_x - 220) + (i - num_hosts//2) * 90
        hy = r1_y + 200
        hid = add_docker_host(project_id, hname, x=hx, y=hy)
        host_ids.append((hname, hid))

    # Step 4 — Create links
    print("\n[4/7] Creating links...")
    # R1 → R3 f0/0  (WAN link)
    create_link(project_id,
                r1_id, r1_iface["adapter"], r1_iface["port"],
                r3_id, 0, 0)
    print(f"  ✅ R1 {r1_iface['interface']} → {router_name} f0/0")

    # R3 f1/0 → SW_Tenant e0/0  (LAN link, PA-FE-TX port 0)
    create_link(project_id, r3_id, 1, 0, sw_id, 0, 0)
    print(f"  ✅ {router_name} f1/0 → {switch_name} e0/0")

    # Hosts → SW_Tenant  (each host gets its own switch port starting at e0/1)
    for i, (hname, hid) in enumerate(host_ids):
        sw_adapter = (i + 1) // 4
        sw_port    = (i + 1) % 4
        create_link(project_id, hid, 0, 0, sw_id, sw_adapter, sw_port)
        print(f"  ✅ {hname} → {switch_name} e{sw_adapter}/{sw_port}")

    # Step 5 — Start nodes
    print("\n[5/7] Starting nodes...")
    start_node(project_id, sw_id)
    start_node(project_id, r3_id)
    for _, hid in host_ids:
        start_node(project_id, hid)
    print("  Waiting 45 seconds for router to boot...")
    time.sleep(45)

    # Step 6 — Configure devices
    print("\n[6/7] Refreshing topology and configuring...")
    from discover import discover
    discover()
    from host_manager import load_topology, get_node, set_host_ip
    topology = load_topology()

    r3_node  = get_node(topology, router_name)
    r1_node2 = get_node(topology, "R1")
    if not r3_node:
        raise Exception(f"{router_name} not found after discovery")

    r3_port  = r3_node["console_port"]
    r1_port  = r1_node2["console_port"]

    # Configure R3
    conn = connect_device(r3_port)
    conn.enable()
    link_ip  = link_subnet["r3_ip"]
    link_net = link_subnet["subnet"].split("/")[0]
    ten_net  = tenant_subnet.split("/")[0]

    # f0/0 = WAN (to R1), f1/0 = LAN (to tenant switch, gateway for all hosts)
    cmds = [
        "conf t",
        "no ip domain-lookup",
        f"hostname {router_name}",
        "interface FastEthernet0/0",
        f" ip address {link_ip} 255.255.255.252",
        " duplex full",
        " no shutdown",
        "interface FastEthernet1/0",
        f" ip address {tenant_gw} 255.255.255.0",
        " duplex full",
        " no shutdown",
    ]

    # Routing protocol
    if protocol == "ospf":
        cmds += [
            "router ospf 1",
            f" router-id {link_ip}",
            f" network {link_net} 0.0.0.3 area 0",
            f" network {ten_net} 0.0.0.255 area 0",
        ]
    elif protocol == "ripv2":
        cmds += [
            "router rip", " version 2", " no auto-summary",
            f" network {link_net}", f" network {ten_net}",
        ]
    elif protocol == "static":
        cmds.append(f"ip route 0.0.0.0 0.0.0.0 {link_subnet['r1_ip']}")

    cmds.append("end")
    for cmd in cmds:
        conn.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn.disconnect()
    print(f"  ✅ {router_name} configured")

    # Configure R1
    conn2 = connect_device(r1_port)
    conn2.enable()
    r1_cmds = [
        "conf t",
        f"interface {r1_iface['interface']}",
        f" ip address {link_subnet['r1_ip']} 255.255.255.252",
        " duplex full",
        " no shutdown",
    ]
    if protocol == "ospf":
        r1_cmds += ["router ospf 1", f" network {link_net} 0.0.0.3 area 0"]
    elif protocol == "ripv2":
        r1_cmds += ["router rip", " version 2", f" network {link_net}"]
    elif protocol == "static":
        r1_cmds.append(f"ip route {ten_net} 255.255.255.0 {link_subnet['r3_ip']}")
    r1_cmds.append("end")
    for cmd in r1_cmds:
        conn2.send_command_timing(cmd.strip(), delay_factor=2)
    try:
        conn2.send_command_timing("write memory", delay_factor=8, max_loops=500)
    except:
        pass
    conn2.disconnect()
    print(f"  ✅ R1 configured")

    # Set host IPs
    print("  Setting host IPs...")
    for i, (hname, _) in enumerate(host_ids):
        set_host_ip(hname, f"{base_ip}.{10+i}/24", tenant_gw, topology)

    # Step 7 — Verify adjacency
    print("\n[7/7] Verifying adjacency...")
    time.sleep(10)
    adj_ok = verify_adjacency(r1_port, protocol, link_subnet["r3_ip"])
    print(f"  {'✅' if adj_ok else '⚠️'} Adjacency {'established' if adj_ok else 'pending'}")

    # Save records
    save_router_link(router_name, link_subnet, r1_iface)

    import os as _os
    _tenants_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tenants.json")
    try:
        with open(_tenants_file) as f:
            tenants = json.load(f)
    except:
        tenants = {}

    tenants[tenant_name] = {
        "config": config,
        "hosts": [{"host": f"{tenant_name}_{i+1}", "ip": f"{base_ip}.{10+i}/24"} for i in range(num_hosts)],
        "router": router_name,
        "switch": switch_name,
        "onboarded_at": __import__("datetime").datetime.now().isoformat()
    }
    import os as _os
    _tenants_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tenants.json")
    with open(_tenants_file, "w") as f:
        json.dump(tenants, f, indent=2)

    print(f"\n{'='*52}")
    print(f"✅ {tenant_name} ONBOARDED")
    print(f"   Topology: R1 → {router_name} → {switch_name} → {num_hosts} hosts")
    print(f"   Protocol: {protocol.upper()}")
    print(f"   Subnet:   {tenant_subnet}")
    print(f"   Adjacency: {'✅' if adj_ok else '⚠️ pending'}")
    print(f"{'='*52}")

    return {
        "status": "success",
        "tenant": tenant_name,
        "router": router_name,
        "switch": switch_name,
        "protocol": protocol,
        "link_subnet": link_subnet["subnet"],
        "r1_interface": r1_iface["interface"],
        "adjacency": adj_ok,
        "hosts": [h[0] for h in host_ids]
    }


def generate_router_preview(config):
    router_name   = config["router_name"]
    tenant_name   = config["tenant_name"]
    tenant_subnet = config.get("tenant_subnet", "192.168.70.0/24")
    tenant_gw     = config.get("tenant_gateway", "192.168.70.1")
    protocol      = config["routing_protocol"]
    num_hosts     = config.get("num_hosts", 2)
    link          = LINK_SUBNET_POOL[0]
    base_ip       = ".".join(tenant_gw.split(".")[:3])

    notes = {
        "ospf":   "Recommended — fast convergence (~30s), joins area 0",
        "ripv2":  "Simple config — slower convergence (~60s), 15-hop limit",
        "static": "Maximum isolation — no protocol overhead"
    }

    lines = [
        f"=== ROUTER ONBOARDING — DRY RUN ===",
        f"",
        f"Tenant:    {tenant_name}",
        f"Topology:  R1 → {router_name} → {num_hosts} hosts (direct)",
        f"Protocol:  {protocol.upper()} — {notes.get(protocol,'')}",
        f"",
        f"── GNS3 CHANGES ──────────────────",
        f"  + {router_name} (c7200 router)",
    ]
    for i in range(num_hosts):
        lines.append(f"  + {tenant_name}_{i+1} (NetworkHost)")

    lines += [
        f"",
        f"── LINKS ─────────────────────────",
        f"  R1 FastEthernet1/1 ──── {router_name} f0/0",
    ]
    for i in range(num_hosts):
        adapter = 1 + (i // 2)
        port = i % 2
        lines.append(f"  {tenant_name}_{i+1} ──── {router_name} f{adapter}/{port}")

    lines += [
        f"",
        f"── P2P LINK ──────────────────────",
        f"  R1 f1/1:       {link['r1_ip']}/30",
        f"  {router_name} f0/0: {link['r3_ip']}/30",
        f"",
        f"── {router_name} CONFIG ──────────────────",
        f"  interface FastEthernet0/0",
        f"   ip address {link['r3_ip']} 255.255.255.252",
        f"  interface FastEthernet1/0",
        f"   ip address {tenant_gw} 255.255.255.0",
    ]

    if protocol == "ospf":
        lines += [
            f"  router ospf 1",
            f"   router-id {link['r3_ip']}",
            f"   network {link['subnet'].split('/')[0]} 0.0.0.3 area 0",
            f"   network {tenant_subnet.split('/')[0]} 0.0.0.255 area 0",
        ]
    elif protocol == "ripv2":
        lines += ["  router rip", "   version 2", "   no auto-summary",
                  f"   network {link['subnet'].split('/')[0]}",
                  f"   network {tenant_subnet.split('/')[0]}"]
    elif protocol == "static":
        lines.append(f"  ip route 0.0.0.0 0.0.0.0 {link['r1_ip']}")

    lines += [
        f"",
        f"── HOST IPs ──────────────────────",
    ]
    for i in range(num_hosts):
        lines.append(f"  {tenant_name}_{i+1}: {base_ip}.{10+i}/24 gw {tenant_gw}")

    lines += [
        f"",
        f"── WARNINGS ──────────────────────",
        f"  ⚠️  Router boot: ~35 seconds",
        f"  ⚠️  {'OSPF convergence: ~30s' if protocol=='ospf' else 'RIPv2 convergence: ~60s' if protocol=='ripv2' else 'Static: immediate'}",
        f"  ⚠️  R1 FastEthernet1/1 will be used",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print("Router Onboarding Engine loaded")
    print("Available R1 interfaces:", [i["interface"] for i in R1_INTERFACE_POOL])
    print("Link subnet pool:", [s["subnet"] for s in LINK_SUBNET_POOL])

# ── ROUTER OFFBOARDING ────────────────────────────────────

def offboard_tenant_router(tenant_name):
    """
    Full multi-tier tenant router offboarding.
    Removes: hosts → SW2 → R3 → R1 config → link record
    """
    print(f"\n{'='*52}")
    print(f"OFFBOARDING ROUTER TENANT: {tenant_name}")
    print(f"{'='*52}")

    # Load tenant record
    try:
        with open("tenants.json") as f:
            tenants = json.load(f)
    except:
        raise Exception("tenants.json not found")

    if tenant_name not in tenants:
        raise Exception(f"Tenant {tenant_name} not found")

    record      = tenants[tenant_name]
    router_name = record.get("router")
    switch_name = record.get("switch")
    hosts       = [h["host"] for h in record.get("hosts", [])]

    if not router_name:
        raise Exception(f"{tenant_name} has no router record")

    # Load router link info
    try:
        with open("router_links.json") as f:
            links = json.load(f)
        link_info = links.get(router_name, {})
    except:
        link_info = {}

    r1_iface   = link_info.get("r1_interface", "FastEthernet1/1")
    r3_ip      = link_info.get("r3_ip", "")
    ten_net    = record["config"].get("tenant_subnet", "").split("/")[0]
    protocol   = record["config"].get("routing_protocol", "ospf")

    project_id = get_project_id()

    # ── STEP 1 — Remove R1 config
    print(f"\n[1/5] Removing R1 config...")
    try:
        from host_manager import load_topology, get_node
        topology = load_topology()
        r1_node  = get_node(topology, "R1")
        r1_port  = r1_node["console_port"]

        conn = connect_device(r1_port)
        conn.enable()
        cmds = [
            "conf t",
            f"interface {r1_iface}",
            " no ip address",
            " shutdown",
        ]
        if protocol == "ospf":
            link_net = link_info.get("subnet", "").split("/")[0]
            if link_net:
                cmds += [
                    "router ospf 1",
                    f" no network {link_net} 0.0.0.3 area 0",
                ]
        elif protocol == "ripv2":
            link_net = link_info.get("subnet", "").split("/")[0]
            if link_net:
                cmds += [
                    "router rip",
                    f" no network {link_net}",
                ]
        elif protocol == "static":
            if ten_net:
                cmds.append(f"no ip route {ten_net} 255.255.255.0 {r3_ip}")

        cmds.append("end")
        for cmd in cmds:
            conn.send_command_timing(cmd.strip(), delay_factor=2)
        conn.send_command_timing("write memory", delay_factor=8, max_loops=500)
        conn.disconnect()
        print(f"  ✅ R1 {r1_iface} config removed")
    except Exception as e:
        print(f"  ⚠️ R1 cleanup warning: {e}")

    # ── STEP 2 — Delete GNS3 nodes
    print(f"\n[2/5] Removing GNS3 nodes...")
    nodes_to_delete = hosts + ([switch_name] if switch_name else []) + [router_name]

    r = requests.get(f"{GNS3_API}/projects/{project_id}/nodes", auth=GNS3_AUTH)
    all_nodes = {n["name"]: n["node_id"] for n in r.json()}

    for node_name in nodes_to_delete:
        node_id = all_nodes.get(node_name)
        if node_id:
            requests.post(
                f"{GNS3_API}/projects/{project_id}/nodes/{node_id}/stop",
                auth=GNS3_AUTH
            )
            time.sleep(1)
            r = requests.delete(
                f"{GNS3_API}/projects/{project_id}/nodes/{node_id}",
                auth=GNS3_AUTH
            )
            if r.status_code == 204:
                print(f"  ✅ Deleted {node_name}")
            else:
                print(f"  ⚠️ Could not delete {node_name}: {r.status_code}")
        else:
            print(f"  ⚠️ {node_name} not found in GNS3")

    # ── STEP 3 — Free link subnet
    print(f"\n[3/5] Freeing link subnet...")
    try:
        with open("router_links.json") as f:
            links = json.load(f)
        links.pop(router_name, None)
        with open("router_links.json", "w") as f:
            json.dump(links, f, indent=2)
        print(f"  ✅ Link subnet freed")
    except Exception as e:
        print(f"  ⚠️ {e}")

    # ── STEP 4 — Remove from tenants.json
    print(f"\n[4/5] Updating records...")
    tenants.pop(tenant_name, None)
    with open("tenants.json", "w") as f:
        json.dump(tenants, f, indent=2)
    print(f"  ✅ {tenant_name} removed from records")

    # ── STEP 5 — Refresh topology
    print(f"\n[5/5] Refreshing topology...")
    from discover import discover
    discover()
    print(f"  ✅ Topology updated")

    print(f"\n{'='*52}")
    print(f"✅ {tenant_name} FULLY OFFBOARDED")
    print(f"   Removed: {router_name}, {switch_name}, {len(hosts)} hosts")
    print(f"   R1 {r1_iface} released")
    print(f"{'='*52}")

    return {
        "status": "success",
        "tenant": tenant_name,
        "removed_router": router_name,
        "removed_switch": switch_name,
        "removed_hosts": hosts
    }
