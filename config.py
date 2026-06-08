"""
config.py — Central configuration for SmartMall Network Automation System
All sensitive values are loaded from environment variables.
Copy .env.example to .env and fill in your values before running.
"""
import os

# GNS3 Connection
GNS3_HOST = os.environ.get("GNS3_HOST", "localhost")
GNS3_PORT = os.environ.get("GNS3_PORT", "80")
GNS3_API  = f"http://{GNS3_HOST}:{GNS3_PORT}/v2"
GNS3_URL  = f"http://{GNS3_HOST}:{GNS3_PORT}"
GNS3_AUTH = (
    os.environ.get("GNS3_USER", "gns3"),
    os.environ.get("GNS3_PASS", "gns3")
)

# Cisco device credentials
CISCO_SECRET   = os.environ.get("CISCO_SECRET", "cisco")
CISCO_PASSWORD = os.environ.get("CISCO_PASSWORD", "")

# API Keys (loaded from environment — never hardcode)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY", "")

# Project
PROJECT_NAME = os.environ.get("GNS3_PROJECT", "SmartMall_x")
