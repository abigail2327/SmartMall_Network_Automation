import json
import os
from groq import Groq
from config import GROQ_API_KEY
from decision_engine import build_tenant_config, load_intent

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are a network automation assistant for a Smart Mall.
Your job is to extract structured intent from admin messages.

The mall has these existing VLANs:
- VLAN 10: Admin (192.168.10.0/24)
- VLAN 20: HStore (192.168.20.0/24)
- VLAN 30: WiFi (192.168.30.0/24)
- VLAN 40: CCTV (192.168.40.0/24)
- VLAN 50: PaymentServers (192.168.50.0/24)

Tenant types and their defaults:
- retail: 2 hosts, internet + payment access, medium QoS
- restaurant: 3 hosts, internet + payment access, medium QoS
- bank: 3 hosts, payment only, high QoS, high security
- food_court: 8 hosts, internet + payment, needs own switch
- anchor: 10+ hosts, full access, needs own switch + router
- popup: 1 host, internet only, temporary (7 days default)

Access options: internet, payment, admin, cctv, all

You must return ONLY valid JSON, no explanation, no markdown:
{
  "action": "add_tenant|remove_tenant|modify_acl|show_status|add_vlan|unknown",
  "tenant_name": "string or null",
  "tenant_type": "retail|restaurant|bank|food_court|anchor|popup or null",
  "num_hosts": number or null,
  "access": ["internet","payment","admin","cctv","all"] or null,
  "qos": "high|medium|low or null",
  "needs_switch": true/false or null,
  "needs_router": true/false or null,
  "duration_days": number or null,
  "vlan_id": number or null,
  "subnet": "string or null",
  "confidence": "high|medium|low",
  "clarification_needed": "string or null"
}"""

def parse_admin_command(message):
    """Parse natural language admin command using Groq."""
    # Get current intent for context
    try:
        intent = load_intent()
        used_vlans = [v["id"] for v in intent["network"]["vlans"]]
        context = f"\nCurrently used VLANs: {used_vlans}"
    except:
        context = ""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + context},
            {"role": "user", "content": message}
        ],
        temperature=0.1,
        max_tokens=500
    )

    raw = response.choices[0].message.content.strip()

    # Clean up response
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    parsed = json.loads(raw)
    return parsed

def process_command(message):
    """Full pipeline: parse NLP → build config → return result."""
    print(f"\nProcessing: '{message}'")

    # Parse with NLP
    parsed = parse_admin_command(message)
    print(f"AI parsed: action={parsed.get('action')}, "
          f"tenant={parsed.get('tenant_name')}, "
          f"type={parsed.get('tenant_type')}, "
          f"hosts={parsed.get('num_hosts')}")

    action = parsed.get("action", "unknown")

    if action == "add_tenant":
        # Build full config with decision engine
        config = build_tenant_config(parsed)

        if not config["safe_to_deploy"]:
            return {
                "status": "conflict",
                "message": f"Conflicts detected: {config['conflicts']}",
                "config": config
            }

        return {
            "status": "ready",
            "action": "add_tenant",
            "config": config,
            "summary": build_summary(config)
        }

    elif action == "remove_tenant":
        return {
            "status": "ready",
            "action": "remove_tenant",
            "tenant_name": parsed.get("tenant_name"),
            "summary": f"Will offboard tenant '{parsed.get('tenant_name')}' — removes VLAN, subinterface, ACL, and GNS3 nodes"
        }

    elif action == "show_status":
        return {
            "status": "ready",
            "action": "show_status",
            "summary": "Running network health check..."
        }

    elif action == "modify_acl":
        return {
            "status": "ready",
            "action": "modify_acl",
            "parsed": parsed,
            "summary": "ACL modification requested — review before applying"
        }

    else:
        clarification = parsed.get("clarification_needed", "Could you clarify what you'd like to do?")
        return {
            "status": "clarification_needed",
            "message": clarification,
            "parsed": parsed
        }

def build_summary(config):
    """Build human-readable summary of what will be deployed."""
    lines = [
        f"Tenant: {config['name']} ({config['tenant_type']})",
        f"VLAN: {config['vlan_id']} — {config['subnet']}",
        f"Gateway: {config['gateway']}",
        f"Hosts: {config['num_hosts']} NetworkHost node(s)",
        f"Access: {', '.join(config['access'])}",
        f"QoS: {config['qos']} priority",
        f"ACL: {config['acl_number']} applied inbound on f0/0.{config['vlan_id']}",
    ]
    if config.get("needs_switch"):
        lines.append(f"Own switch: {config.get('switch_name')} will be added")
    if config.get("needs_router"):
        lines.append(f"Own router: {config.get('router_name')} will be added")
    if config.get("duration_days"):
        lines.append(f"Duration: {config['duration_days']} days (auto-offboard scheduled)")
    return "\n".join(lines)

if __name__ == "__main__":
    # Test the NLP engine
    test_commands = [
        "Add a coffee shop with 2 terminals and payment access",
        "Add a bank branch with 5 hosts, payment only, high security",
        "Add a food court with 8 terminals and their own switch",
        "Add a pop-up stall for 7 days, internet only",
        "Remove CoffeeShop",
    ]

    for cmd in test_commands:
        print(f"\n{'='*50}")
        result = process_command(cmd)
        print(f"Status: {result['status']}")
        if result.get('summary'):
            print(f"Summary:\n{result['summary']}")
        if result.get('message'):
            print(f"Message: {result['message']}")
