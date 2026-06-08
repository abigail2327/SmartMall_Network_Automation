"""
Scheduler — background jobs for SmartMall automation
- Auto-offboard timed tenants
- Hourly health check
- Config backup every 6 hours
"""
import threading
from config import GNS3_HOST, CISCO_SECRET
import time
import json
import datetime
import os

_scheduled_offboards = {}  # {tenant_name: offboard_timestamp}

def schedule_offboard(tenant_name, days):
    """Schedule a tenant to be offboarded after N days."""
    offboard_at = datetime.datetime.now() + datetime.timedelta(days=days)
    _scheduled_offboards[tenant_name] = offboard_at.isoformat()
    save_schedule()
    print(f"[SCHEDULER] {tenant_name} scheduled for offboard on {offboard_at.strftime('%Y-%m-%d %H:%M')}")
    return offboard_at.isoformat()

def cancel_offboard(tenant_name):
    """Cancel a scheduled offboard."""
    if tenant_name in _scheduled_offboards:
        del _scheduled_offboards[tenant_name]
        save_schedule()
        print(f"[SCHEDULER] Offboard cancelled for {tenant_name}")
        return True
    return False

def save_schedule():
    with open("schedule.json", "w") as f:
        json.dump(_scheduled_offboards, f, indent=2)

def load_schedule():
    global _scheduled_offboards
    try:
        with open("schedule.json") as f:
            _scheduled_offboards = json.load(f)
        print(f"[SCHEDULER] Loaded {len(_scheduled_offboards)} scheduled jobs")
    except:
        _scheduled_offboards = {}

def check_offboards():
    """Check if any tenants need to be offboarded."""
    now = datetime.datetime.now()
    to_offboard = []

    for tenant_name, offboard_at_str in list(_scheduled_offboards.items()):
        try:
            offboard_at = datetime.datetime.fromisoformat(offboard_at_str)
            if now >= offboard_at:
                to_offboard.append(tenant_name)
        except:
            pass

    for tenant_name in to_offboard:
        print(f"[SCHEDULER] Auto-offboarding {tenant_name}...")
        try:
            from tenant import offboard_tenant
            result = offboard_tenant(tenant_name)
            if result["status"] == "success":
                del _scheduled_offboards[tenant_name]
                save_schedule()
                print(f"[SCHEDULER] ✅ {tenant_name} auto-offboarded")
            else:
                print(f"[SCHEDULER] ❌ {tenant_name} offboard failed")
        except Exception as e:
            print(f"[SCHEDULER] ❌ Error offboarding {tenant_name}: {e}")

def backup_configs():
    """Save running configs to backup file."""
    try:
        from netmiko import ConnectHandler
        backup = {}
        devices = {"R1": 5000, "R2": 5001, "SW1": 5002}
        for name, port in devices.items():
            try:
                conn = ConnectHandler(
                    device_type="cisco_ios_telnet",
                    host=GNS3_HOST, port=port,
                    username="", password="", secret=CISCO_SECRET,
                    timeout=30
                )
                conn.enable()
                backup[name] = conn.send_command("show running-config")
                conn.disconnect()
            except Exception as e:
                backup[name] = f"ERROR: {e}"

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backups/config_backup_{timestamp}.json"
        os.makedirs("backups", exist_ok=True)
        with open(filename, "w") as f:
            json.dump(backup, f, indent=2)
        print(f"[SCHEDULER] Config backup saved: {filename}")
    except Exception as e:
        print(f"[SCHEDULER] Backup failed: {e}")

def run_scheduler():
    """Main scheduler loop."""
    load_schedule()
    print("[SCHEDULER] Starting background scheduler...")

    last_backup = datetime.datetime.now()
    check_count = 0

    while True:
        time.sleep(60)  # Check every minute
        check_count += 1

        # Check auto-offboards every minute
        check_offboards()

        # Config backup every 6 hours
        if (datetime.datetime.now() - last_backup).seconds >= 21600:
            backup_configs()
            last_backup = datetime.datetime.now()

        if check_count % 60 == 0:  # Log every hour
            print(f"[SCHEDULER] Running — {len(_scheduled_offboards)} scheduled jobs")

def start_scheduler():
    """Start scheduler in background thread."""
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    print("[SCHEDULER] Started")
    return t

def get_scheduled_jobs():
    """Return current scheduled jobs."""
    return {
        name: {
            "offboard_at": ts,
            "days_remaining": max(0, (datetime.datetime.fromisoformat(ts) - datetime.datetime.now()).days)
        }
        for name, ts in _scheduled_offboards.items()
    }

if __name__ == "__main__":
    print("Scheduler test:")
    schedule_offboard("TestTenant", 7)
    print(get_scheduled_jobs())
