# -*- coding: utf-8 -*-
"""
server.py — jednoduchý Flask server pro spouštění QuickTips skriptu
--------------------------------------------------------------------
- endpoint /run-morning  → spustí quicktips.py a vrátí text tiketu
- endpoint /run-evening  → spustí evaluate_quicktips.py a vrátí vyhodnocení

Spustíš:  python server.py
"""

from flask import Flask, Response
import subprocess

app = Flask(name)

@app.route("/run-morning")
def run_morning():
    try:
        result = subprocess.run(["python", "quicktips.py"], capture_output=True, text=True, timeout=60)
        return Response(result.stdout, mimetype="text/plain")
    except Exception as e:
        return Response(f"Chyba: {e}", mimetype="text/plain")

@app.route("/run-evening")
def run_evening():
    try:
        result = subprocess.run(["python", "evaluate_quicktips.py"], capture_output=True, text=True, timeout=90)
        return Response(result.stdout, mimetype="text/plain")
    except Exception as e:
        return Response(f"Chyba: {e}", mimetype="text/plain")

@app.route("/")
def home():
    return "✅ QuickTips server běží!"

if name == "main":   # ← OPRAVENÝ ŘÁDEK
    app.run(host="0.0.0.0", port=10000)
