import json
import os
from groq import Groq
from config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

def generate_configs():
    with open("intent.json") as f:
        intent = json.load(f)

    network = intent["network"]
    vlans = network["vlans"]
    ospf = network["ospf"]
    acls = network["acls"]
    qos = network["qos"]
    inter_vlan = network["inter_vlan_routing"]
    constraints = network.get("constraints", "")

    vlan_summary = "\n".join([f"  VLAN {v['id']} ({v['name']}): subnet {v['subnet']}, gateway {v['gateway']}" for v in vlans])
    acl_summary = "\n".join([f"  {a['action'].upper()} from {a['src']} to {a['dst']} applied inbound on R1 {a['apply_on']}" for a in acls])
    ivlan_summary = "\n".join([f"  {iv['subinterface']}: VLAN {iv['vlan']}, encapsulation {iv['encapsulation']}" for iv in inter_vlan])

    prompt = f"""You are a Cisco IOS network engineer. Generate complete CLI configurations for a Smart Mall network.

TOPOLOGY:
- R1 (c7200): Core mall router. f0/0 = trunk to SW1. f1/0 = link to R2 ({ospf['r1_link_ip']})
- R2 (c7200): Edge/internet router. f0/0 = link to R1 ({ospf['r2_link_ip']})
- SW1 (Cisco IOU L2): Mall switch.
  - e0/0 = Admin (VLAN 10)
  - e0/1 = HStore (VLAN 20)
  - e0/2 = WiFi (VLAN 30)
  - e0/3 = CCTV (VLAN 40)
  - e1/0 = PaymentServers (VLAN 50)
  - e1/1 = trunk to R1 f0/0

VLANS:
{vlan_summary}

INTER-VLAN ROUTING (router-on-a-stick on R1 f0/0):
{ivlan_summary}

OSPF:
- Process ID: {ospf['process_id']}, Area: {ospf['area']}
- R1 router-id: {ospf['r1_router_id']}, IP on f1/0: {ospf['r1_link_ip']}
- R2 router-id: {ospf['r2_router_id']}, IP on f0/0: {ospf['r2_link_ip']}
- Link subnet: {ospf['link_subnet']}
- Wildcard: {ospf['wildcard']}
- Advertise all VLAN subnets and the R1-R2 link into OSPF

ACL RULES (extended ACLs on R1, applied inbound on subinterfaces):
{acl_summary}
- Each subinterface gets its own numbered ACL (100 for f0/0.10, 120 for f0/0.20, 130 for f0/0.30, 140 for f0/0.40, 150 for f0/0.50)
- CRITICAL: ACL 100 (Admin VLAN) must ONLY contain: permit ip any any — Admin has FULL access, NO deny rules
- Always end each ACL with: permit ip any any

QOS:
- High priority: {qos[0]['traffic']}
- Medium priority: {qos[1]['traffic']}
- Best effort: {qos[2]['traffic']}
- Use MQC (class-map + policy-map) on R1
- Class names: CRITICAL, MANAGEMENT, BEST-EFFORT

EXTRA CONSTRAINTS: {constraints if constraints else 'None'}

Generate THREE separate complete configs. Use this EXACT format:

===R1_CONFIG===
(complete R1 config here)

===R2_CONFIG===
(complete R2 config here)

===SW1_CONFIG===
(complete SW1 config here)

CRITICAL RULES — FOLLOW EXACTLY:
- R1: Use "no shutdown" on ALL interfaces including f0/0, f1/0 and all subinterfaces
- R1: f0/0 must have "no ip address" and "no shutdown"
- R1: f1/0 must have "no shutdown" explicitly
- R2: f0/0 must have "no shutdown" explicitly
- SW1 is Cisco IOU L2 — trunk port e1/1 MUST use these exact commands in this order:
    switchport trunk encapsulation dot1q
    switchport mode trunk
    switchport trunk allowed vlan 1-4094
    no shutdown
- SW1 access ports: switchport mode access, switchport access vlan X, no shutdown
- Include "write memory" at end of each config
- Do NOT include any explanation, only CLI commands
- Do NOT use markdown code blocks
"""

    print("Sending intent to Groq AI...")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=4000
    )

    raw = response.choices[0].message.content
    print("Response received. Parsing configs...")

    configs = {}
    for device, marker in [("R1", "===R1_CONFIG==="), ("R2", "===R2_CONFIG==="), ("SW1", "===SW1_CONFIG===")]:
        if marker in raw:
            start = raw.index(marker) + len(marker)
            next_markers = [m for m in ["===R1_CONFIG===", "===R2_CONFIG===", "===SW1_CONFIG==="] if m != marker and m in raw[start:]]
            if next_markers:
                end = raw.index(next_markers[0], start)
                configs[device] = raw[start:end].strip()
            else:
                configs[device] = raw[start:].strip()
        else:
            configs[device] = f"ERROR: {marker} not found in response"

    # Post-process: force correct ACL 100 for Admin
    if "R1" in configs:
        lines = configs["R1"].splitlines()
        new_lines = []
        in_acl_100 = False
        skip_until_next = False
        for line in lines:
            stripped = line.strip()
            if "ip access-list extended 100" in stripped:
                in_acl_100 = True
                skip_until_next = True
                new_lines.append(line)
                new_lines.append(" permit ip any any")
                continue
            if in_acl_100 and skip_until_next:
                if stripped.startswith("ip access-list") or stripped.startswith("interface") or stripped.startswith("router") or stripped == "!":
                    in_acl_100 = False
                    skip_until_next = False
                    new_lines.append(line)
                continue
            new_lines.append(line)
        configs["R1"] = "\n".join(new_lines)

    # Post-process: force correct SW1 trunk on e1/1
    if "SW1" in configs:
        lines = configs["SW1"].splitlines()
        new_lines = []
        in_e11 = False
        for line in lines:
            stripped = line.strip()
            if "interface Ethernet1/1" in stripped or "interface ethernet1/1" in stripped.lower():
                in_e11 = True
                new_lines.append(line)
                continue
            if in_e11:
                if stripped.startswith("interface") and "1/1" not in stripped:
                    in_e11 = False
                    new_lines.append(line)
                    continue
                if "switchport mode trunk" in stripped and "encapsulation" not in stripped:
                    new_lines.append(" switchport trunk encapsulation dot1q")
                    new_lines.append(" switchport mode trunk")
                    new_lines.append(" switchport trunk allowed vlan 1-4094")
                    new_lines.append(" no shutdown")
                    continue
                if "switchport trunk encapsulation" in stripped:
                    continue
                if "switchport trunk allowed" in stripped:
                    continue
            new_lines.append(line)
        configs["SW1"] = "\n".join(new_lines)

    output = {
        "generated_by": "Groq llama-3.3-70b-versatile",
        "project": "SmartMall_x",
        "devices": configs,
        "raw_response": raw
    }

    with open("configs.json", "w") as f:
        json.dump(output, f, indent=2)

    print("configs.json saved!")
    print(f"  R1 config: {len(configs.get('R1','').splitlines())} lines")
    print(f"  R2 config: {len(configs.get('R2','').splitlines())} lines")
    print(f"  SW1 config: {len(configs.get('SW1','').splitlines())} lines")

    return output

if __name__ == "__main__":
    generate_configs()
