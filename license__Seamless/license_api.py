# -*- coding: utf-8 -*-
"""
License Check API — Flask endpoint.
The main Seamless/ConfigFlow bots call this API every hour to verify their license.

Endpoint:  GET /api/check?token=BOT_TOKEN
Response:  {"valid": true/false, "plan": "...", "expires_at": ..., "remaining_hours": ...}
"""
import time
from flask import Flask, request, jsonify
from bot.db import get_active_license_by_token

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Seamless License API"})


@app.route("/api/check", methods=["GET"])
def check_license():
    token = request.args.get("token", "").strip()
    if not token or ":" not in token:
        return jsonify({"valid": False, "error": "missing or invalid token"}), 400

    lic = get_active_license_by_token(token)
    if not lic:
        return jsonify({"valid": False, "error": "no active license found"}), 200

    remaining = lic["expires_at"] - time.time()
    if remaining <= 0:
        return jsonify({"valid": False, "error": "license expired"}), 200

    return jsonify({
        "valid": True,
        "license_id": lic["id"],
        "plan": lic["plan"],
        "bot_username": lic["bot_username"],
        "expires_at": lic["expires_at"],
        "remaining_hours": round(remaining / 3600, 1),
    }), 200
