# SmartMall AI-Assisted Network Automation System

An intelligent, conversational network management system for a smart mall environment. Instead of CLI commands, a network admin types in plain English — and the system configures VLANs, onboards tenants, applies ACLs, and self-heals when things break.

Built for NSSA 443 — Network Design & Performance, RIT Dubai (Spring 2026).

---

## Features

- **Network Brain** — Conversational AI powered by Claude Sonnet, translating plain English into Cisco IOS commands
- **Closed-Loop Correction Engine** — Detects, diagnoses, and auto-fixes misconfigurations without human intervention
- **Dynamic Tenant Onboarding/Offboarding** — Automated VLAN, subnet, ACL, and GNS3 node management
- **Automated Scheduler** — Auto-offboard temporary tenants (pop-ups, kiosks) after lease expiry
- **Routing Protocol Engine** — Switch between OSPF, RIPv2, and Static routing via chat
- **Multi-Tier Router Onboarding** — Dedicated router + switch for anchor store tenants
- **IP Persistence Heartbeat** — Monitors and restores Docker host IPs every 10 minutes
- **Override System** — Logs and applies policy-violating changes when admin insists
- **Full Audit Logs** — Deployment logs, correction logs, validation reports

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Network Simulator | GNS3 |
| Router Image | Cisco c7200 (IOS 15.3) |
| Switch Image | Cisco IOU L2 |
| Hosts | Docker (nicolaka/netshoot) |
| AI Engine | Anthropic Claude Sonnet + Groq LLaMA |
| Automation | Python + Netmiko (Telnet) |
| Backend | Flask |

---

## Network Design

5 trust zones via VLAN segmentation on a router-on-a-stick architecture:

| VLAN | Name | Subnet | Policy |
|------|------|--------|--------|
| 10 | Admin | 192.168.10.0/24 | Full access |
| 20 | HStore | 192.168.20.0/24 | Internet + Payment |
| 30 | WiFi | 192.168.30.0/24 | Internet only |
| 40 | CCTV | 192.168.40.0/24 | Admin access only |
| 50 | Payment | 192.168.50.0/24 | Restricted DMZ |

---

## Setup

### 1. Prerequisites

- GNS3 VM running with SmartMall_x project loaded
- Python 3.10+
- Anthropic API key
- Groq API key

### 2. Install dependencies

```bash
pip install flask anthropic groq netmiko requests
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your GNS3 VM IP and API keys
```

### 4. Run

```bash
python app.py
```

Open `http://localhost:5050` in your browser.

---

## Project Structure

```
├── app.py                  # Flask server + all API routes
├── brain.py                # Claude AI conversation engine
├── correction_engine.py    # Closed-loop self-healing
├── tenant.py               # Tenant onboard/offboard
├── router_onboarding.py    # Multi-tier router onboarding
├── routing_engine.py       # OSPF/RIPv2/Static management
├── decision_engine.py      # VLAN/subnet/port allocation
├── deploy.py               # Baseline config deployment
├── discover.py             # GNS3 topology discovery
├── generate.py             # AI config generation (Groq)
├── validate_network.py     # Network validation + ACL tests
├── validate_intent.py      # Intent JSON validation
├── host_manager.py         # Docker host IP management
├── heartbeat.py            # IP persistence monitor
├── scheduler.py            # Auto-offboard scheduler
├── nlp_engine.py           # Legacy NLP (Groq)
├── config.py               # Central config (env-based)
├── .env.example            # Environment variable template
└── topology.example.json   # Topology file template
```

---

## Team

| Name | Contribution |
|------|-------------|
| Abigail Da Costa | Configuration & development (35%) |
| Fahim Faisal | Configuration & development (33%) |
| Yahya Elsawi | Documentation & error handling (16%) |
| Lewam Yohannes | Documentation & error handling (8%) |
| Deneb A Malek | Documentation & error handling (8%) |

---

## Limitations

- IPv4 only (no IPv6 support)
- Cisco devices only (no multi-vendor)
- Single-site topology (no WAN/BGP)
- No RBAC — all admins have full access
- Concurrent onboarding requests not supported
- Tested on small lab topology, not production scale
