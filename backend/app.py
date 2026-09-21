"""
Backend mínimo de MediPass.

Expone GET /api/equivalences, que lee la vista `equivalences` (definida en
schema.sql) y la devuelve como JSON. Incluye forma, dosis, composición, ATC y
foto de cada producto, que fetch_cima.py ya guardó en medipass.db.
"""

import gzip
import json
import os
import sqlite3

from flask import Flask, Response, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "medipass.db")


@app.get("/api/equivalences")
def equivalences():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # El orden es explícito para que el producto "representativo" de cada país
    # sea siempre el mismo (el primero por nombre) entre una carga y otra.
    rows = conn.execute(
        "SELECT * FROM equivalences ORDER BY inn_name, form, country_code, brand_name"
    ).fetchall()
    conn.close()

    body = json.dumps([dict(row) for row in rows], ensure_ascii=False, separators=(",", ":"))
    body = body.encode("utf-8")
    headers = {"Vary": "Accept-Encoding"}

    # El catálogo completo pesa ~450 KB en JSON. Se comprime (~10x menos) por
    # ancho de banda y porque en algunas máquinas Windows las respuestas
    # grandes por localhost se cortan a medias y la conexión se cuelga ~19 s.
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"

    return Response(body, mimetype="application/json", headers=headers)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
