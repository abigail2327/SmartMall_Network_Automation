<div align="center">

```
███████╗███╗   ███╗ █████╗ ██████╗ ████████╗███╗   ███╗ █████╗ ██╗     ██╗
██╔════╝████╗ ████║██╔══██╗██╔══██╗╚══██╔══╝████╗ ████║██╔══██╗██║     ██║
███████╗██╔████╔██║███████║██████╔╝   ██║   ██╔████╔██║███████║██║     ██║
╚════██║██║╚██╔╝██║██╔══██║██╔══██╗   ██║   ██║╚██╔╝██║██╔══██║██║     ██║
███████║██║ ╚═╝ ██║██║  ██║██║  ██║   ██║   ██║ ╚═╝ ██║██║  ██║███████╗███████╗
╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝
```

### **AI-Assisted Network Automation System**
*Conversational intelligence for smart mall network infrastructure*

---

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude_Sonnet-AI_Engine-CC785C?style=for-the-badge&logo=anthropic&logoColor=white)
![Cisco](https://img.shields.io/badge/Cisco_IOS-15.3-1BA0D7?style=for-the-badge&logo=cisco&logoColor=white)
![GNS3](https://img.shields.io/badge/GNS3-Network_Sim-FF6C37?style=for-the-badge)
![License](https://img.shields.io/badge/License-Academic-green?style=for-the-badge)

**NSSA 443 — Network Design & Performance · RIT Dubai · Spring 2026**

[Features](#features) · [Architecture](#architecture) · [Network Design](#network-design) · [Setup](#setup) · [Usage](#usage) · [Validation](#validation-results)

</div>

---

## What Is This?

SmartMall is a full-stack AI-assisted network automation system that replaces manual Cisco CLI configuration with a **conversational interface**. Instead of typing IOS commands, a network administrator types in plain English — and the system handles everything: VLAN creation, ACL enforcement, tenant onboarding, fault detection, and self-healing.

```
Admin: "Add a bank branch with 3 terminals, payment access only, high security"

System: → Assigns VLAN 60, subnet 192.168.60.0/24
        → Creates 3 Docker hosts in GNS3
        → Configures R1 subinterface f0/0.60 with dot1Q encapsulation
        → Generates and applies extended ACL 160 (payment-only policy)
        → Advertises subnet via OSPF
        → Sets IPs on all hosts
        → Confirms: "BankBranch onboarded. VLAN 60, 3 hosts, ACL 160 applied."
```

This is a working proof-of-concept, not a demo — every action above executes live on Cisco IOS devices in GNS3.

---

## Features

### Network Brain
The core intelligence — powered by **Claude Sonnet**. Accepts plain English, returns structured JSON actions, and drives the entire automation pipeline.

Five operation modes:

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| **Advisory** | Default | Explains decisions, flags policy violations, asks before acting |
| **Dry Run** | "plan it", "preview" | Generates full CLI preview without deploying |
| **Deploy** | "deploy", confirmation | Executes the planned configuration |
| **Override** | "do it anyway" | Logs violation, applies change despite policy conflict |
| **Fix** | "fix it", "fix all" | Triggers closed-loop correction engine |

---

### Closed-Loop Correction Engine
The system detects failures, diagnoses root cause, applies a delta fix, and revalidates — all without human intervention.

```
[1] Validate  →  detect failures
[2] Collect evidence from R1, R2, SW1
[3] Send to Claude → receive targeted fix plan
[4] Apply delta config to affected devices
[5] Revalidate → if still failing, repeat (max 3 loops)
```

Real result from testing:
```
Attempt 1: 3/10 pings passed  →  7 failures detected
Attempt 2: 6/10 pings passed  →  4 failures remain
Attempt 3: 10/10 pings passed →  all checks passed
```

---

### Dynamic Tenant Onboarding / Offboarding

Full lifecycle management. Each onboarding automatically:

- Assigns the next available VLAN ID (starting from 60)
- Creates subnet, gateway, and ACL number
- Provisions Docker host nodes in GNS3
- Configures SW1 access ports
- Adds R1 subinterface with dot1Q encapsulation
- Generates and applies extended ACL based on tenant access policy
- Advertises new subnet via OSPF
- Persists tenant record to `tenants.json`

Supported tenant types:

| Type | Hosts | Default Access | QoS |
|------|-------|---------------|-----|
| `retail` | 2 | Internet + Payment | Medium |
| `restaurant` | 3 | Internet + Payment | Medium |
| `bank` | 3 | Payment only | High |
| `food_court` | 8 | Internet + Payment | Medium |
| `anchor` | 10+ | Full access | High |
| `popup` | 1 | Internet only | Low |

---

### Routing Protocol Engine
Switch routing protocols mid-conversation:

```
Admin: "Change OSPF router ID on R1 to 3.3.3.3"
Admin: "Migrate to RIPv2"
Admin: "Show me a dry run first"
Admin: "Go back to OSPF"
```

Supports **OSPF**, **RIPv2**, and **Static** routing — with dry-run preview before any deployment.

---

### Multi-Tier Router Onboarding
For anchor stores requiring dedicated infrastructure:

```
R1 ──── R3 (tenant router) ──── SW_Tenant ──── hosts × N
```

The system provisions the full topology: c7200 router, IOU L2 switch, Docker hosts, all links, and routing adjacency — from a single chat message.

---

### Automated Scheduler
Tenants can be onboarded with a lease timer:

```
Admin: "Add QuickBite food stall for 3 days, internet only"
```

A background thread checks every 60 seconds and auto-offboards when the lease expires — removing VLAN, ACL, subinterface, GNS3 nodes, and tenant record automatically.

---

### IP Persistence Heartbeat
Docker containers lose their IP on restart. A background thread monitors all base hosts and tenant hosts every 10 minutes, restoring lost IPs automatically. Logged on every restoration.

---

### Override System
When a change violates security policy, the brain warns clearly. If the admin persists, the override is executed **and logged** with timestamp, action details, and the exact command that triggered it.

```json
{
  "timestamp": "2026-04-20T21:32:57",
  "action": "merge_vlans",
  "details": "Admin merged VLAN 40 (CCTV) into VLAN 50 (Payment) — security policy violation",
  "triggered_by": "I understand, but do it anyway"
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                       │
│              index.html · JS · CSS · Chat UI                │
│         Live Topology Panel · Active Tenants Panel          │
└──────────────────────┬──────────────────────────────────────┘
                       │ REST API (Flask)
┌──────────────────────▼──────────────────────────────────────┐
│                    INTELLIGENCE LAYER                        │
│         brain.py ←→ Claude Sonnet API (Anthropic)          │
│    Intent parsing · Mode detection · Config generation      │
└──────┬───────────────┬──────────────────┬───────────────────┘
       │               │                  │
┌──────▼──────┐ ┌──────▼──────┐ ┌────────▼────────┐
│  tenant.py  │ │correction_  │ │ routing_engine  │
│  Onboard /  │ │ engine.py   │ │ router_onboard  │
│  Offboard   │ │ Self-heal   │ │ Protocol mgmt   │
└──────┬──────┘ └──────┬──────┘ └────────┬────────┘
       │               │                  │
┌──────▼───────────────▼──────────────────▼───────────────────┐
│                   AUTOMATION LAYER                           │
│          Python + Netmiko (Telnet-based SSH)                │
│           GNS3 REST API (node/link provisioning)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  INFRASTRUCTURE LAYER                        │
│    GNS3 VM · R1 (c7200) · R2 (c7200) · SW1 (IOU L2)       │
│              Docker Hosts (nicolaka/netshoot)               │
└─────────────────────────────────────────────────────────────┘
```

### Component Map

| File | Role |
|------|------|
| `app.py` | Flask server, all API routes |
| `brain.py` | Claude Sonnet conversation engine |
| `correction_engine.py` | Closed-loop fault detection and remediation |
| `tenant.py` | Tenant onboard / offboard full pipeline |
| `router_onboarding.py` | Multi-tier router topology provisioning |
| `routing_engine.py` | OSPF / RIPv2 / Static protocol management |
| `decision_engine.py` | VLAN, subnet, port allocation logic |
| `deploy.py` | Baseline config deployment to devices |
| `discover.py` | GNS3 topology discovery via REST API |
| `generate.py` | AI config generation (Groq LLaMA) |
| `validate_network.py` | Full network validation — pings, iperf3, router checks |
| `validate_intent.py` | Intent JSON semantic validation |
| `host_manager.py` | Docker host IP assignment via raw socket |
| `heartbeat.py` | Background IP persistence monitor |
| `scheduler.py` | Auto-offboard scheduler for timed tenants |
| `nlp_engine.py` | Legacy NLP parser (Groq) |
| `config.py` | Centralised environment-based configuration |

---

## Network Design

### Topology

```
                    ┌──────────────────┐
                    │       R2         │  (Edge / Internet Gateway)
                    │   10.0.0.2/30    │
                    └────────┬─────────┘
                             │ OSPF f0/0
                    ┌────────┴─────────┐
                    │       R1         │  (Core / router-on-a-stick)
                    │   10.0.0.1/30    │
                    │  f0/0 → trunk    │
                    └────────┬─────────┘
                             │ dot1Q trunk (f0/0 → e1/1)
                    ┌────────┴─────────┐
                    │      SW1         │  (Distribution Switch)
          ┌─────────┼──────────────────┼─────────────────┐
          │         │                  │                  │
     e0/0 │    e0/1 │             e0/2 │            e0/3  │   e1/0
    ┌─────┴──┐ ┌────┴───┐       ┌─────┴──┐       ┌──────┴┐ ┌────────────┐
    │ Admin  │ │ HStore │       │  WiFi  │       │  CCTV │ │  Payment   │
    │VLAN 10 │ │VLAN 20 │       │VLAN 30 │       │VLAN 40│ │  VLAN 50  │
    └────────┘ └────────┘       └────────┘       └───────┘ └────────────┘
```

### VLAN Trust Zones

| VLAN | Name | Subnet | Gateway | Security Policy |
|------|------|--------|---------|----------------|
| 10 | Admin | 192.168.10.0/24 | .10.1 | Full access — `permit ip any any` |
| 20 | HStore | 192.168.20.0/24 | .20.1 | Internet + Payment access |
| 30 | WiFi | 192.168.30.0/24 | .30.1 | Internet only — Admin & Payment blocked |
| 40 | CCTV | 192.168.40.0/24 | .40.1 | Admin access only — Payment blocked |
| 50 | Payment | 192.168.50.0/24 | .50.1 | Restricted DMZ |

### OSPF Configuration

```
Process ID : 1, Area 0
R1 router-id: 1.1.1.1   R1 f1/0: 10.0.0.1/30
R2 router-id: 2.2.2.2   R2 f0/0: 10.0.0.2/30
Advertised: all VLAN subnets + R1-R2 link
```

### QoS Priority

```
HIGH    → Payment (VLAN 50)           — priority queuing
MEDIUM  → Admin (VLAN 10), CCTV (40)  — 30% bandwidth guarantee
LOW     → WiFi (VLAN 30), HStore (20) — best effort
```

---

## Setup

### Prerequisites

- GNS3 VM running with `SmartMall_x` project loaded and all devices started
- Python 3.10+
- Anthropic API key ([console.anthropic.com](https://console.anthropic.com))
- Groq API key ([console.groq.com](https://console.groq.com))

### Install

```bash
git clone https://github.com/abigail2327/SmartMall_Network_Automation.git
cd SmartMall_Network_Automation

pip install flask anthropic groq netmiko requests
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
GNS3_HOST=192.168.x.x        # Your GNS3 VM IP
GNS3_PORT=80
GNS3_USER=gns3
GNS3_PASS=gns3
GNS3_PROJECT=SmartMall_x
CISCO_SECRET=cisco
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
```

### Run

```bash
python app.py
```

Open **http://localhost:5050** in your browser.

---

## Usage

### First-Time Setup

```
1. Click "Discover" → scans GNS3 and builds topology.json
2. Type: "Set up the network"
3. Claude generates intent, configs, and deploys to all devices
4. Hosts are auto-configured with IPs on startup
```

### Example Chat Commands

```bash
# Onboarding
"Add a coffee shop with 2 terminals and payment access"
"Add a bank branch, 3 hosts, payment only, high security"
"Add a food court with 8 terminals, their own switch"
"Add a pop-up stall for 7 days, internet only"

# Anchor stores (multi-tier)
"Add Carrefour as an anchor store with their own router, 10 hosts"

# Routing
"Change OSPF router ID on R1 to 3.3.3.3"
"Migrate to RIPv2 — show me a dry run first"
"Change back to OSPF"

# Fixing
"Fix all"
"Fix only the ACLs"

# Offboarding
"Remove the coffee shop"
"Offboard BankBranch"

# Custom IPs
"Set Admin host IP to 192.168.10.25"
```

### API Endpoints

| Method | Endpoint | Action |
|--------|----------|--------|
| POST | `/brain/chat` | Send message to AI brain |
| POST | `/tenant/onboard` | Onboard a tenant |
| POST | `/tenant/offboard` | Offboard a tenant |
| POST | `/correct` | Trigger correction engine |
| POST | `/router/onboard` | Onboard router tenant |
| POST | `/routing/change` | Change routing protocol |
| GET | `/tenants` | List active tenants |
| GET | `/topology` | Get current topology |
| GET | `/validation_report` | Get last validation report |
| GET | `/correction_log` | Get correction history |

---

## Validation Results

All results from live testing on the GNS3 lab.

### ACL Policy Tests — 10/10 Passed

| Test | Expected | Result | Latency |
|------|----------|--------|---------|
| Admin → HStore | Allow | PASS | 23.7ms |
| Admin → Payment | Allow | PASS | 17.0ms |
| Admin → WiFi | Allow | PASS | 22.9ms |
| WiFi → Admin | Block | PASS | — |
| WiFi → Payment | Block | PASS | — |
| WiFi → HStore | Allow | PASS | — |
| HStore → Payment | Allow | PASS | — |
| CCTV → Admin | Allow | PASS | — |
| CCTV → Payment | Block | PASS | — |
| Payment → Admin | Allow | PASS | — |

### Infrastructure Checks

| Component | Status |
|-----------|--------|
| VLANs (10, 20, 30, 40, 50) | PASS |
| OSPF adjacency (R1 ↔ R2) | PASS |
| Routing table (all subnets) | PASS |
| QoS policy (MQC) | PASS |
| Extended ACLs | PASS |

### Closed-Loop Correction Test

```
Scenario: ACL 130 (WiFi isolation) manually removed
Before correction: 3/10 pings passed
After correction:  10/10 pings passed
Loops required:    3
Total time:        ~7 minutes
```

### iperf3 Throughput

| Flow | Throughput |
|------|-----------|
| HStore → Payment (high priority) | ~7.3 Mbits/sec |
| WiFi → Admin | N/A (ACL blocked — expected) |

---

## Limitations

| Limitation | Detail |
|-----------|--------|
| IPv4 only | No IPv6 / dual-stack support |
| Cisco only | No multi-vendor (JunOS, Nokia, etc.) |
| Single site | No WAN, BGP, or multi-site |
| No RBAC | All admins have full access |
| No concurrency | Simultaneous onboard requests may conflict |
| Lab scale | Tested on small topology, not production |
| Token cost | Complex operations: $0.50–$2.00 per prompt |

---

## Future Work

- **IPv6 dual-stack** — full IPv4/IPv6 support across all VLANs
- **Parallel validation** — replace sequential pings with `asyncio` for 5x speed
- **SQLite scheduler** — persist scheduled jobs across Flask restarts
- **Mobile companion app** — push notifications for topology changes
- **Digital twin** — test config changes before applying to live network
- **Predictive analytics** — ML model to forecast ACL/OSPF failures before they occur
- **Voice-to-text** — hands-free network management
- **Multi-vendor** — Netmiko integration for JunOS, Nokia SR-OS
- **BGP support** — multi-site mall deployments via conversational interface

---

**Course:** NSSA 443 — Network Design & Performance · **Instructor:** Dr. Mohamed Abdelraheem · **RIT Dubai, Spring 2026**
