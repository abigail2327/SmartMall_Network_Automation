from flask import Flask, render_template, request, jsonify
from heartbeat import start_heartbeat
from scheduler import start_scheduler
import json
import os
import threading
import time

app = Flask(__name__)

# ── AUTO HOST CONFIGURATION ON STARTUP ──────────────────
def auto_configure_hosts():
    def run():
        time.sleep(8)
        try:
            from host_manager import load_topology, configure_all_hosts, set_host_ip, get_node
            topology = load_topology()

            # Configure base hosts
            with open("intent.json") as f:
                intent = json.load(f)
            print("[STARTUP] Auto-configuring base host IPs...")
            results = configure_all_hosts(topology, intent)
            ok = sum(1 for r in results if r["status"] == "success")
            print(f"[STARTUP] Base hosts: {ok}/{len(results)} configured")

            # Configure tenant hosts
            if os.path.exists("tenants.json"):
                with open("tenants.json") as f:
                    tenants = json.load(f)
                tenant_count = 0
                tenant_ok = 0
                for tenant_name, record in tenants.items():
                    config = record.get("config", {})
                    gateway = config.get("gateway", "")
                    host_list = record.get("hosts", [])
                    for host in host_list:
                        host_name = host.get("host", "")
                        host_ip = host.get("ip", "")
                        if not host_ip.endswith("/24"):
                            host_ip += "/24"
                        node = get_node(topology, host_name)
                        if node and host_name and host_ip and gateway:
                            tenant_count += 1
                            result = set_host_ip(host_name, host_ip, gateway, topology)
                            if result["status"] == "success":
                                tenant_ok += 1
                if tenant_count > 0:
                    print(f"[STARTUP] Tenant hosts: {tenant_ok}/{tenant_count} configured")
        except Exception as e:
            print(f"[STARTUP] Host config failed: {e}")
    threading.Thread(target=run, daemon=True).start()

if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    start_heartbeat()
    start_scheduler()
    auto_configure_hosts()

# ── BASIC ROUTES ─────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/discover", methods=["POST"])
def run_discover():
    try:
        from discover import discover
        topology = discover()
        return jsonify({"status": "success", "topology": topology})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/topology", methods=["GET"])
def get_topology():
    if os.path.exists("topology.json"):
        with open("topology.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "topology.json not found"})

@app.route("/intent", methods=["POST"])
def save_intent():
    try:
        data = request.json
        with open("topology.json") as f:
            topology = json.load(f)
        intent = {
            "project": "SmartMall_x",
            "topology": topology,
            "network": {
                "vlans": data.get("vlans", []),
                "ospf": data.get("ospf", {}),
                "inter_vlan_routing": data.get("inter_vlan_routing", []),
                "acls": data.get("acls", []),
                "qos": data.get("qos", []),
                "constraints": data.get("constraints", "")
            }
        }
        with open("intent.json", "w") as f:
            json.dump(intent, f, indent=2)
        return jsonify({"status": "success", "intent": intent})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/intent", methods=["GET"])
def get_intent():
    if os.path.exists("intent.json"):
        with open("intent.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "intent.json not found"})

@app.route("/validate", methods=["POST"])
def validate():
    try:
        from validate_intent import validate_intent
        if not os.path.exists("intent.json"):
            return jsonify({"status": "error", "message": "intent.json not found"})
        with open("intent.json") as f:
            intent = json.load(f)
        result = validate_intent(intent)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/generate", methods=["POST"])
def generate():
    try:
        from generate import generate_configs
        if not os.path.exists("intent.json"):
            return jsonify({"status": "error", "message": "intent.json not found"})
        result = generate_configs()
        return jsonify({"status": "success", "configs": result["devices"],
                        "generated_by": result["generated_by"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/configs", methods=["GET"])
def get_configs():
    if os.path.exists("configs.json"):
        with open("configs.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "configs.json not found"})

@app.route("/deploy", methods=["POST"])
def deploy():
    try:
        from deploy import deploy_all
        if not os.path.exists("configs.json"):
            return jsonify({"status": "error", "message": "configs.json not found"})
        result = deploy_all()
        summary = {}
        for device, log in result["devices"].items():
            summary[device] = {
                "status": log["status"],
                "commands_sent": len(log.get("commands", [])),
                "errors": len([c for c in log.get("commands", []) if c.get("status") == "error"]),
                "verification": log.get("verification", {}),
                "error_message": log.get("error", "")
            }
        return jsonify({"status": "success", "summary": summary,
                        "timestamp": result["timestamp"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/deployment_log", methods=["GET"])
def get_deployment_log():
    if os.path.exists("deployment_log.json"):
        with open("deployment_log.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "deployment_log.json not found"})

# ── VALIDATION ───────────────────────────────────────────
@app.route("/validate_network", methods=["POST"])
def validate_network():
    try:
        from validate_network import run_full_validation
        result = run_full_validation()
        return jsonify({"status": "success", "report": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/validation_report", methods=["GET"])
def get_validation_report():
    if os.path.exists("validation_report.json"):
        with open("validation_report.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No validation report found"})

# ── TENANT MANAGEMENT ────────────────────────────────────
@app.route("/tenant/onboard", methods=["POST"])
def tenant_onboard():
    try:
        from tenant import onboard_tenant
        config = request.json
        result = onboard_tenant(config)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/tenant/offboard", methods=["POST"])
def tenant_offboard():
    try:
        from tenant import offboard_tenant
        data = request.json
        tenant_name = data.get("tenant_name")
        result = offboard_tenant(tenant_name)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/tenant/preview_config", methods=["POST"])
def tenant_preview_config():
    try:
        from tenant import generate_preview
        from decision_engine import build_tenant_config
        data = request.json
        if data.get("message"):
            from nlp_engine import process_command
            result = process_command(data["message"])
            if result["status"] == "ready" and result["action"] == "add_tenant":
                config = result["config"]
            else:
                return jsonify({"status": "error",
                                "message": result.get("message", "Could not parse")})
        else:
            config = build_tenant_config(data)
        preview = generate_preview(config)
        return jsonify({"status": "success", "preview": preview, "config": config})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/tenants", methods=["GET"])
def get_tenants():
    try:
        from tenant import load_all_tenant_records
        records = load_all_tenant_records()
        return jsonify({"status": "success", "tenants": records})
    except Exception as e:
        return jsonify({"status": "success", "tenants": {}})

# ── HOST MANAGEMENT ──────────────────────────────────────
@app.route("/hosts/configure", methods=["POST"])
def configure_hosts():
    try:
        from host_manager import load_topology, configure_all_hosts
        topology = load_topology()
        with open("intent.json") as f:
            intent = json.load(f)
        results = configure_all_hosts(topology, intent)
        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ── NLP (LEGACY — kept for compatibility) ────────────────
@app.route("/nlp", methods=["POST"])
def nlp_command():
    try:
        from nlp_engine import process_command
        data = request.json
        message = data.get("message", "")
        if not message:
            return jsonify({"status": "error", "message": "No message"})
        result = process_command(message)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ── CLAUDE BRAIN ROUTES ──────────────────────────────────
@app.route("/brain/chat", methods=["POST"])
def brain_chat():
    try:
        from brain import brain
        data = request.json
        message = data.get("message", "")
        if not message:
            return jsonify({"status": "error", "message": "No message"})
        result = brain.chat(message)

        # If Claude says fix — trigger correction engine
        if result.get("action") in ["fix_all", "fix_acls", "fix_ospf", "fix_vlans"]:
            scope_map = {
                "fix_all": "all",
                "fix_acls": "acls",
                "fix_ospf": "ospf",
                "fix_vlans": "vlans"
            }
            result["correction_triggered"] = True
            result["correction_scope"] = scope_map.get(result["action"], "all")

        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/brain/confirm", methods=["POST"])
def brain_confirm():
    try:
        from brain import brain
        result = brain.confirm_pending()
        if result:
            return jsonify({"status": "success", "result": result})
        return jsonify({"status": "error", "message": "No pending action"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/brain/reset", methods=["POST"])
def brain_reset():
    try:
        from brain import brain
        brain.reset_conversation()
        return jsonify({"status": "success", "message": "Conversation reset"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/brain/history", methods=["GET"])
def brain_history():
    try:
        from brain import brain
        return jsonify({"status": "success",
                        "history": brain.conversation_history})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/overrides", methods=["GET"])
def get_overrides():
    try:
        with open("overrides.json") as f:
            return jsonify(json.load(f))
    except:
        return jsonify([])

# ── CUSTOM HOST IP ──────────────────────────────────────
@app.route("/hosts/set_ip", methods=["POST"])
def set_custom_host_ip():
    try:
        from host_manager import load_topology, set_host_ip
        data = request.json
        host_configs = data.get("host_configs", [])
        topology = load_topology()
        results = []
        for hc in host_configs:
            result = set_host_ip(
                hc["host_name"],
                hc["ip_cidr"],
                hc["gateway"],
                topology
            )
            results.append(result)
        return jsonify({"status": "success", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ── ROUTER ONBOARDING ───────────────────────────────────
@app.route("/router/onboard", methods=["POST"])
def router_onboard():
    try:
        from router_onboarding import onboard_tenant_router
        config = request.json
        result = onboard_tenant_router(config)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/router/preview", methods=["POST"])
def router_preview():
    try:
        from router_onboarding import generate_router_preview
        config = request.json
        preview = generate_router_preview(config)
        return jsonify({"status": "success", "preview": preview})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/router/offboard", methods=["POST"])
def router_offboard():
    try:
        from router_onboarding import offboard_tenant_router
        data = request.json
        result = offboard_tenant_router(data.get("tenant_name"))
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ── ROUTING ENGINE ──────────────────────────────────────
@app.route("/routing/status", methods=["GET"])
def routing_status():
    try:
        from routing_engine import get_current_routing_config
        config = get_current_routing_config()
        return jsonify({"status": "success", "config": config})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/routing/change", methods=["POST"])
def routing_change():
    try:
        from routing_engine import (migrate_to_ripv2, migrate_to_ospf,
                                     change_ospf_config, generate_ripv2_preview,
                                     generate_ospf_preview)
        data = request.json
        action = data.get("routing_action")
        changes = data.get("routing_changes", {})
        dry_run = data.get("dry_run", False)

        if action == "migrate_to_ripv2":
            if dry_run:
                preview = generate_ripv2_preview()
                return jsonify({"status": "success", "preview": preview, "dry_run": True})
            result = migrate_to_ripv2()
            return jsonify({"status": "success", "result": result})

        elif action == "migrate_to_ospf":
            if dry_run:
                return jsonify({"status": "success",
                    "preview": "=== RESTORE OSPF (DRY RUN) ===\nno router rip\nrouter ospf 1\n router-id 1.1.1.1\n network ...",
                    "dry_run": True})
            result = migrate_to_ospf()
            return jsonify({"status": "success", "result": result})

        elif action == "change_ospf_config":
            if dry_run:
                preview = generate_ospf_preview(changes)
                return jsonify({"status": "success", "preview": preview, "dry_run": True})
            result = change_ospf_config(changes)
            return jsonify({"status": "success", "result": result})

        else:
            return jsonify({"status": "error", "message": f"Unknown action: {action}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ── CORRECTION ENGINE ───────────────────────────────────
_correction_jobs = {}  # job_id -> {status, result, error}

@app.route("/correct", methods=["POST"])
def correct_network():
    import uuid
    from correction_engine import run_correction
    data = request.json or {}
    scope = data.get("scope", "all")
    max_retries = data.get("max_retries", 3)
    job_id = str(uuid.uuid4())[:8]

    _correction_jobs[job_id] = {"status": "running", "scope": scope, "result": None, "error": None}

    def _run():
        try:
            result = run_correction(scope=scope, max_retries=max_retries)
            _correction_jobs[job_id]["status"] = "done"
            _correction_jobs[job_id]["result"] = result
        except Exception as e:
            _correction_jobs[job_id]["status"] = "error"
            _correction_jobs[job_id]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "job_id": job_id})

@app.route("/correct/status/<job_id>", methods=["GET"])
def correction_status(job_id):
    job = _correction_jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Job not found"})
    if job["status"] == "running":
        return jsonify({"status": "running"})
    if job["status"] == "error":
        return jsonify({"status": "error", "message": job["error"]})
    return jsonify({"status": "success", "result": job["result"]})

@app.route("/correction_log", methods=["GET"])
def get_correction_log():
    if os.path.exists("correction_log.json"):
        with open("correction_log.json") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No correction log found"})

# ── SCHEDULER ────────────────────────────────────────────
@app.route("/scheduler/jobs", methods=["GET"])
def get_scheduler_jobs():
    from scheduler import get_scheduled_jobs
    return jsonify({"status": "success", "jobs": get_scheduled_jobs()})

@app.route("/scheduler/cancel", methods=["POST"])
def cancel_scheduled_job():
    from scheduler import cancel_offboard
    data = request.json
    result = cancel_offboard(data.get("tenant_name"))
    return jsonify({"status": "success" if result else "error"})

# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5050)
