"""
Backend mínimo de MediPass.

Expone GET /api/equivalences, que lee la vista `equivalences` (definida en
schema.sql) y la devuelve como JSON. Incluye forma, dosis, composición, ATC,
foto y estatus legal (libre / solo farmacia / receta) de cada producto.

INTERRUPTOR DE RECETAS: la variable de entorno INCLUDE_PRESCRIPTION decide si la API
sirve los medicamentos CON receta.
    INCLUDE_PRESCRIPTION=1   (por defecto) sirve todo; la app marca los de receta en rojo
    INCLUDE_PRESCRIPTION=0   solo sirve los sin receta (como antes de añadirlos)
Se apaga sin reimportar nada: los datos siguen en medipass.db. Está pensado para poder
publicar la app sin medicamentos con receta si un abogado lo recomienda (ver README,
"Alcance legal"). GET /api/config dice en qué modo está, y la app adapta sus textos.

    set INCLUDE_PRESCRIPTION=0   (Windows)   &&   python app.py
"""

import gzip
import json
import os
import sqlite3

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "medipass.db")
INCLUDE_PRESCRIPTION = os.environ.get("INCLUDE_PRESCRIPTION", "1").strip().lower() not in ("0", "false", "no", "off")


@app.get("/api/config")
def config():
    return jsonify({"include_prescription": INCLUDE_PRESCRIPTION})


@app.get("/api/equivalences")
def equivalences():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Con el interruptor apagado no sale NADA con receta (ni como producto ni como grupo).
    # Los desconocidos (NULL) se tratan como sin receta: son los ejemplos manuales.
    where = "" if INCLUDE_PRESCRIPTION else "WHERE COALESCE(requires_prescription, 0) = 0"
    # El orden es explícito para que el producto "representativo" de cada país
    # sea siempre el mismo (el primero por nombre) entre una carga y otra.
    rows = conn.execute(
        f"SELECT * FROM equivalences {where} ORDER BY inn_name, form, country_code, brand_name"
    ).fetchall()
    conn.close()

    body = json.dumps([dict(row) for row in rows], ensure_ascii=False, separators=(",", ":"))
    body = body.encode("utf-8")
    headers = {"Vary": "Accept-Encoding"}

    # El catálogo completo pesa varios MB en JSON. Se comprime (~10x menos) por
    # ancho de banda y porque en algunas máquinas Windows las respuestas
    # grandes por localhost se cortan a medias y la conexión se cuelga ~19 s.
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"

    return Response(body, mimetype="application/json", headers=headers)


if __name__ == "__main__":
    # Con waitress (pip install waitress) las respuestas grandes salen en menos de un segundo.
    # El servidor de desarrollo de Flask en Windows se cuelga ~19 s con respuestas de más de
    # unos 50 KB (aunque vayan comprimidas): con el catálogo con recetas (~6 MB) es inservible.
    try:
        from waitress import serve
    except ImportError:
        print("[aviso] waitress no está instalado: usando el servidor de desarrollo de Flask, que puede ir muy lento. "
              "Instálalo con: pip install waitress")
        app.run(debug=True, port=5000)
    else:
        print("MediPass backend en http://127.0.0.1:5000 (waitress)")
        serve(app, host="127.0.0.1", port=5000)
