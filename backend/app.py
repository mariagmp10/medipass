"""
Backend mínimo de MediPass.

Expone GET /api/equivalences, que lee la vista `equivalences` (definida en
schema.sql) y la devuelve como JSON para que el frontend deje de usar el
array MEDS en memoria.

También expone GET /api/product-detail/<nregistro>, que consulta en vivo la
API de CIMA (no medipass.db) para traer dosis, forma farmacéutica y una foto
real del envase. Solo tiene sentido para productos españoles, que son los
únicos con número de registro real.
"""

import os
import sqlite3

import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "medipass.db")
CIMA_BASE = "https://cima.aemps.es/cima/rest"


@app.get("/api/equivalences")
def equivalences():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM equivalences").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.get("/api/product-detail/<nregistro>")
def product_detail(nregistro):
    resp = requests.get(f"{CIMA_BASE}/medicamento", params={"nregistro": nregistro}, timeout=10)
    if not resp.ok:
        return jsonify({"error": "not_found"}), 404

    data = resp.json()
    fotos = data.get("fotos") or []
    foto_url = next((f["url"] for f in fotos if f.get("tipo") == "formafarmac"), None)
    if not foto_url and fotos:
        foto_url = fotos[0].get("url")

    return jsonify(
        {
            "dosis": data.get("dosis"),
            "forma_farmaceutica": (data.get("formaFarmaceutica") or {}).get("nombre"),
            "foto_url": foto_url,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
