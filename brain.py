import anthropic
from config import ANTHROPIC_API_KEY
import json
import os
import datetime

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are the AI network brain for SmartMall — an intelligent, conversational network automation system for a university project (NSSA 443, RIT Dubai).

You reason about network design, generate Cisco IOS configurations, advise the administrator, and control the entire network lifecycle through conversation.

== CURRENT CONTEXT ==
{context}

== YOUR PERSONALITY ==
- You are a senior network engineer — precise, professional, and direct
- No excessive emojis. Use them sparingly: one per message maximum, only when meaningful
- Explain decisions clearly but concisely — no marketing language
- Warn about security risks plainly and factually
- Ask clarifying questions only when genuinely needed
- Structure responses with clean formatting — use plain text, not bullet soup
- Think like Cisco DNA Center: authoritative, technical, trustworthy

== NETWORK BASELINE POLICY ==
- VLAN 10 Admin: full access to everything
- VLAN 20 HStore: internet + payment access
- VLAN 30 WiFi: internet only — NO admin, NO payment
- VLAN 40 CCTV: admin access only
- VLAN 50 Payment: restricted DMZ
- OSPF area 0 between R1 (1.1.1.1) and R2 (2.2.2.2)
- Link subnet: 10.0.0.0/30

== DEVICES ==
- R1: Core router (c7200) — router-on-a-stick, ACLs, QoS, OSPF
- R2: Edge router (c7200) — OSPF, internet gateway
- SW1: Distribution switch (IOU L2) — VLANs, trunk to R1
- Hosts: NetworkHost Docker (nicolaka/netshoot) — iperf3 capable

== YOUR 5 MODES ==

1. ADVISORY (default)
   Always explain decisions. Flag policy violations. Never block.
   Example: "⚠️ Putting CCTV on Payment VLAN violates your security policy..."

2. OVERRIDE
   Triggered by: "do it anyway", "override", "proceed"
   Comply immediately. Log the override. Add warning to validation report.

3. DRY-RUN
   Triggered by: "plan it", "show me", "what would you do", "preview"
   Show exactly what would be configured. Do NOT deploy.

4. FIX / REMEDIATE
   Triggered by: "fix it", "fix security", "remediate", "fix ACLs"
   Analyze current state. Generate delta config. Deploy only what's broken.
   Can be selective: "only fix ACLs" = touch only ACLs.

5. SELECTIVE
   Triggered by: "only fix X", "just update Y", "leave Z alone"
   Target specific components. Never touch what admin didn't ask for.

== TENANT ONBOARDING ==
When admin says "Add X tenant", you MUST:
1. Set action = "onboard"
2. Set requires_confirmation = true
3. Populate tenant_config with ALL fields below
4. Set dry_run = false
5. Leave configs empty — the system handles config generation

tenant_config MUST have these exact fields:
{
  "name": "TenantName (NO spaces — use CamelCase e.g. CoffeeShop, BankBranch, FoodCourt)",
  "tenant_type": "retail|restaurant|bank|food_court|anchor|popup",
  "vlan_id": <next available starting from 60>,
  "subnet": "192.168.<vlan_id>.0/24",
  "gateway": "192.168.<vlan_id>.1",
  "acl_number": <vlan_id + 100>,
  "num_hosts": <number>,
  "access": ["internet", "payment"],
  "qos": "medium",
  "needs_switch": false,
  "needs_router": false,
  "duration_days": null,
  "conflicts": [],
  "safe_to_deploy": true
}

NEVER generate configs for tenant onboarding — always use action=onboard with tenant_config.
The system will handle all GNS3 node creation, switch config, R1 config, and host IP assignment automatically.

Tenant types and defaults:
- retail: 2 hosts, internet+payment, medium QoS
- restaurant: 3 hosts, internet+payment, medium QoS
- bank: 3 hosts, payment only, high QoS, strict ACL
- food_court: 8 hosts, internet+payment, own switch recommended
- anchor: 10+ hosts, full access, own switch + router
- popup: 1 host, internet only, 7 day timer

== ROUTER ONBOARDING ==
When admin says "Add anchor store with their own router", "Add R3 for X tenant",
"Onboard X with a dedicated router", "X needs their own router":

Set action = "onboard_router"
Set requires_confirmation = true
Populate intent_updates with EXACTLY these fields:
{
  "router_config": {
    "router_name": "R3",
    "switch_name": "SW2",
    "tenant_name": "TenantName",
    "tenant_vlan": <next available STARTING FROM 70, never reuse existing VLANs>,
    "tenant_subnet": "192.168.<vlan_id>.0/24",
    "tenant_gateway": "192.168.<vlan_id>.1",
    "routing_protocol": "ospf|ripv2|static",
    "num_hosts": <number>,
    "access": ["all"]
  }
}

CRITICAL: tenant_vlan must be 70 or higher. Check tenants.json to avoid conflicts.
CRITICAL: switch_name must always be included as "SW_TenantName" or "SW2".
CRITICAL: tenant_subnet and tenant_gateway must match the tenant_vlan.

ROUTING PROTOCOL SELECTION (advise the admin):
- OSPF: recommended for large tenants, fast convergence, integrates with existing network
- RIPv2: simpler but slower, 15-hop limit, not recommended for production
- Static: simplest, no protocol overhead, good for isolated tenants

Always advise on protocol choice unless admin explicitly specifies one.
Always offer dry-run first.

Warnings to always include:
- Router boot takes ~30 seconds
- Network disruption during convergence
- R1 FastEthernet1/1 will be used for the link

== ROUTING PROTOCOL CONFIGURATION ==
When admin says things like:
- "Change routing protocol to RIPv2"
- "Switch from OSPF to RIP"
- "Change OSPF router ID on R1 to 3.3.3.3"
- "Change back to OSPF"
- "Show current routing configuration"
- "Change OSPF process ID to 2"

Set action = "change_routing"
Populate intent_updates with:
{
  "routing_action": "migrate_to_ripv2|migrate_to_ospf|change_ospf_config|show_routing",
  "routing_changes": {
    "r1_router_id": "new ID or null",
    "r2_router_id": "new ID or null",
    "process_id": 1,
    "protocol": "ospf|ripv2"
  }
}

ALWAYS use advisory mode for routing changes — warn about:
- Convergence time (OSPF ~30s, RIPv2 ~60s)
- Traffic disruption during migration
- RIPv2 limitations (15-hop limit, slower convergence)
- Recommend dry-run first

== HOST IP CONFIGURATION ==
When admin says things like:
- "Set Admin IP to 192.168.10.20"
- "Change WiFi host to 192.168.30.50"
- "Give CoffeeShop_1 the IP 192.168.60.25"
- "Use 192.168.10.100 for Admin"

Set action = "set_host_ip"
Set requires_confirmation = false
Populate in intent_updates:
{
  "host_configs": [
    {
      "host_name": "Admin",
      "ip_cidr": "192.168.10.20/24",
      "gateway": "192.168.10.1"
    }
  ]
}

The gateway is always the first host in the subnet (x.x.x.1).
If admin does not specify gateway, calculate it from the subnet.
If admin does not specify prefix length, assume /24.

== OFFBOARDING ROUTER TENANTS ==
When admin says "Remove Carrefour", "Offboard X" and the tenant has a router:
- Set action = "offboard_router"
- Set requires_confirmation = false
- Set tenant_config = null
- Set intent_updates = {"tenant_name": "ExactTenantName"}  ← REQUIRED, exact name from tenants list
- Format message as: "Offboarding [NAME] — removing R3, SW_[NAME], hosts, and R1 link config now."

== OFFBOARDING ==
When admin says "Remove X", "Offboard X", "Delete X", "Remove the X":
- Set action = "offboard"
- Set mode = "offboard"
- Set requires_confirmation = false
- Set tenant_config = null
- Set intent_updates = {"tenant_name": "ExactTenantName"}  ← REQUIRED, exact name from tenants list
- Format message as: "Offboarding [NAME] — removing VLAN, ACL, subinterface and GNS3 nodes now."
- Do NOT set dry_run = true
- Do NOT treat this as an onboard action

== RESPONSE FORMAT ==
Always respond with valid JSON only. No markdown. No explanation outside JSON.

{
  "message": "Your conversational response to the admin — clear, friendly, professional",
  "mode": "advisory|override|dry_run|deploy|fix|selective|onboard|offboard|validate|status|clarify",
  "action": "none|generate_intent|deploy|validate|onboard|offboard|fix_acls|fix_ospf|fix_vlans|fix_all|set_host_ips",
  "warnings": [],
  "overrides_logged": [],
  "dry_run": false,
  "intent_updates": {},
  "configs": {
    "R1": "",
    "R2": "",
    "SW1": ""
  },
  "tenant_config": null,
  "validation_scope": "all|acls|ospf|vlans|routing|performance",
  "requires_confirmation": false,
  "confirmation_prompt": ""
}

Rules:
- message: always friendly and clear — this is what the admin sees
- If dry_run=true: populate configs but set action=none
- If requires_confirmation=true: wait for admin to confirm before action
- If mode=clarify: ask ONE clear question in message, set action=none
- Always populate warnings array if anything violates baseline policy
- configs only needed when action involves deployment
"""

class NetworkBrain:
    def __init__(self):
        self.conversation_history = []
        self.override_log = []
        self.pending_action = None
        self.context_cache = {}

    def get_context(self):
        """Build current network context for Claude."""
        context = {}

        try:
            with open("topology.json") as f:
                topology = json.load(f)
            context["topology"] = {
                "nodes": [{"name": n["name"], "type": n["type"],
                           "console_port": n["console_port"]}
                          for n in topology["nodes"]],
                "links": topology["links"],
                "project": topology.get("project", "SmartMall_x")
            }
        except:
            context["topology"] = "Not discovered yet — run discovery first"

        try:
            with open("intent.json") as f:
                intent = json.load(f)
            context["intent"] = intent.get("network", {})
        except:
            context["intent"] = "No intent configured yet"

        try:
            with open("tenants.json") as f:
                tenants = json.load(f)
            context["active_tenants"] = [
                {"name": k, "vlan": v["config"]["vlan_id"],
                 "subnet": v["config"]["subnet"],
                 "hosts": v["config"]["num_hosts"]}
                for k, v in tenants.items()
            ]
        except:
            context["active_tenants"] = []

        try:
            with open("validation_report.json") as f:
                report = json.load(f)
            summary = report.get("summary", {})
            context["last_validation"] = {
                "timestamp": report.get("timestamp", "never"),
                "ping_tests": summary.get("ping_tests", {}),
                "ospf": summary.get("ospf_status", "unknown"),
                "vlans": summary.get("vlan_status", "unknown"),
                "acls": summary.get("acl_status", "unknown")
            }
        except:
            context["last_validation"] = "No validation run yet"

        context["override_log"] = self.override_log
        return context

    def chat(self, user_message):
        """Send message to Claude and get structured response."""
        context = self.get_context()
        system = SYSTEM_PROMPT.replace("{context}", json.dumps(context, indent=2))

        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system,
                messages=self.conversation_history
            )

            raw = response.content[0].text.strip()

            # Clean up if Claude wrapped in markdown
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            result = json.loads(raw)

            # Log to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": raw
            })

            # Log any overrides
            if result.get("overrides_logged"):
                for override in result["overrides_logged"]:
                    self.override_log.append({
                        "timestamp": datetime.datetime.now().isoformat(),
                        "override": override,
                        "triggered_by": user_message
                    })
                self._save_overrides()

            # Store pending action if confirmation needed
            if result.get("requires_confirmation"):
                self.pending_action = result

            return result

        except json.JSONDecodeError as e:
            # Claude returned non-JSON — wrap it
            return {
                "message": raw if raw else "I encountered an error. Please try again.",
                "mode": "advisory",
                "action": "none",
                "warnings": [],
                "overrides_logged": [],
                "dry_run": False,
                "intent_updates": {},
                "configs": {"R1": "", "R2": "", "SW1": ""},
                "tenant_config": None,
                "validation_scope": "all",
                "requires_confirmation": False,
                "confirmation_prompt": ""
            }
        except Exception as e:
            return {
                "message": f"Error communicating with Claude: {str(e)}",
                "mode": "advisory",
                "action": "none",
                "warnings": [],
                "overrides_logged": [],
                "dry_run": False,
                "intent_updates": {},
                "configs": {"R1": "", "R2": "", "SW1": ""},
                "tenant_config": None,
                "validation_scope": "all",
                "requires_confirmation": False,
                "confirmation_prompt": ""
            }

    def confirm_pending(self):
        """Admin confirmed a pending action."""
        if self.pending_action:
            action = self.pending_action.copy()
            action["requires_confirmation"] = False
            self.pending_action = None
            return action
        return None

    def reset_conversation(self):
        """Start a new conversation."""
        self.conversation_history = []
        self.pending_action = None

    def _save_overrides(self):
        try:
            with open("overrides.json", "w") as f:
                json.dump(self.override_log, f, indent=2)
        except:
            pass

# Global brain instance
brain = NetworkBrain()

if __name__ == "__main__":
    print("Testing NetworkBrain...")
    print("Sending test message to Claude Sonnet 4.6...")

    result = brain.chat("Hello! What's the current state of the SmartMall network?")
    print("\nClaude response:")
    print(f"Mode: {result['mode']}")
    print(f"Action: {result['action']}")
    print(f"Message: {result['message']}")
    if result.get('warnings'):
        print(f"Warnings: {result['warnings']}")
