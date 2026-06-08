import json
import ipaddress

def validate_intent(intent):
    errors = []
    warnings = []
    network = intent.get("network", {})
    vlans = network.get("vlans", [])
    acls = network.get("acls", [])
    topology = intent.get("topology", {})
    nodes = topology.get("nodes", [])
    links = topology.get("links", [])
    inter_vlan = network.get("inter_vlan_routing", [])
    ospf = network.get("ospf", {})

    # --- CHECK 1: Duplicate VLAN IDs ---
    vlan_ids = [v["id"] for v in vlans]
    seen = set()
    for vid in vlan_ids:
        if vid in seen:
            errors.append(f"Duplicate VLAN ID detected: {vid}")
        seen.add(vid)

    # --- CHECK 2: Duplicate VLAN Names ---
    vlan_names = [v["name"] for v in vlans]
    seen_names = set()
    for name in vlan_names:
        if name in seen_names:
            errors.append(f"Duplicate VLAN name detected: {name}")
        seen_names.add(name)

    # --- CHECK 3: Valid subnet assignments ---
    subnets = []
    for v in vlans:
        try:
            net = ipaddress.IPv4Network(v["subnet"], strict=False)
            # Check gateway is within subnet
            gw = ipaddress.IPv4Address(v["gateway"])
            if gw not in net:
                errors.append(f"VLAN {v['id']} ({v['name']}): gateway {v['gateway']} is not within subnet {v['subnet']}")
            subnets.append((v["id"], v["name"], net))
        except ValueError as e:
            errors.append(f"VLAN {v['id']} ({v['name']}): invalid subnet — {e}")

    # --- CHECK 4: Overlapping subnets ---
    for i in range(len(subnets)):
        for j in range(i+1, len(subnets)):
            id1, name1, net1 = subnets[i]
            id2, name2, net2 = subnets[j]
            if net1.overlaps(net2):
                errors.append(f"Subnet overlap: VLAN {id1} ({name1}) {net1} overlaps with VLAN {id2} ({name2}) {net2}")

    # --- CHECK 5: OSPF link subnet valid ---
    try:
        ospf_net = ipaddress.IPv4Network(ospf.get("link_subnet",""), strict=False)
        r1_ip = ipaddress.IPv4Address(ospf.get("r1_link_ip",""))
        r2_ip = ipaddress.IPv4Address(ospf.get("r2_link_ip",""))
        if r1_ip not in ospf_net:
            errors.append(f"OSPF: R1 link IP {r1_ip} not within link subnet {ospf_net}")
        if r2_ip not in ospf_net:
            errors.append(f"OSPF: R2 link IP {r2_ip} not within link subnet {ospf_net}")
        if r1_ip == r2_ip:
            errors.append("OSPF: R1 and R2 link IPs are the same")
    except ValueError as e:
        errors.append(f"OSPF: invalid link subnet or IP — {e}")

    # --- CHECK 6: OSPF router IDs unique ---
    if ospf.get("r1_router_id") == ospf.get("r2_router_id"):
        errors.append(f"OSPF: R1 and R2 have the same router ID ({ospf.get('r1_router_id')})")

    # --- CHECK 7: Inter-VLAN subinterfaces match VLANs ---
    ivlan_vlan_ids = []
    for iv in inter_vlan:
        vlan_str = iv.get("vlan", "").split("—")[0].strip().split(" ")[0].strip()
        ivlan_vlan_ids.append(vlan_str)
    for vid in vlan_ids:
        if vid not in ivlan_vlan_ids:
            warnings.append(f"VLAN {vid} has no inter-VLAN subinterface defined — it won't be routable")

    # --- CHECK 8: ACL source/dest are valid subnets ---
    for i, acl in enumerate(acls):
        src = acl.get("src","")
        dst = acl.get("dst","")
        if dst != "any":
            try:
                ipaddress.IPv4Network(src, strict=False)
                ipaddress.IPv4Network(dst, strict=False)
            except ValueError as e:
                errors.append(f"ACL rule {i+1}: invalid IP address — {e}")

    # --- CHECK 9: ACL apply_on interface exists in inter-VLAN ---
    ivlan_interfaces = [iv.get("subinterface","") for iv in inter_vlan]
    for i, acl in enumerate(acls):
        apply_on = acl.get("apply_on","")
        if apply_on and apply_on not in ivlan_interfaces:
            warnings.append(f"ACL rule {i+1}: apply_on interface '{apply_on}' not found in inter-VLAN subinterfaces")

    # --- CHECK 10: Conflicting ACL rules ---
    seen_rules = {}
    for i, acl in enumerate(acls):
        key = (acl.get("src"), acl.get("dst"), acl.get("apply_on"))
        if key in seen_rules:
            errors.append(f"Conflicting ACL rules: rule {seen_rules[key]+1} and rule {i+1} have same src/dst/interface with different actions")
        else:
            seen_rules[key] = i

    # --- CHECK 11: Topology has required devices ---
    node_names = [n["name"] for n in nodes]
    for required in ["R1", "R2", "SW1"]:
        if required not in node_names:
            errors.append(f"Required device '{required}' not found in topology")

    # --- CHECK 12: Trunk link exists SW1 → R1 ---
    trunk_found = False
    for link in links:
        a, b = link.get("device_a",""), link.get("device_b","")
        if (a == "SW1" and b == "R1") or (a == "R1" and b == "SW1"):
            trunk_found = True
    if not trunk_found:
        errors.append("No trunk link found between SW1 and R1 — inter-VLAN routing will not work")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "vlans_checked": len(vlans),
            "acls_checked": len(acls),
            "subinterfaces_checked": len(inter_vlan),
            "topology_nodes": len(nodes),
            "topology_links": len(links)
        }
    }

if __name__ == "__main__":
    with open("intent.json") as f:
        intent = json.load(f)
    result = validate_intent(intent)
    print(json.dumps(result, indent=2))
