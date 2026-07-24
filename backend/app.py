"""
Backend mínimo de MediPass.

Expone GET /api/equivalences, que lee la vista `equivalences` (definida en
schema.sql) y la devuelve como JSON para que el frontend deje de usar el
array MEDS en memoria.
"""

import os
import sqlite3

from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "medipass.db")


@app.get("/api/equivalences")
def equivalences():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM equivalences").fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
