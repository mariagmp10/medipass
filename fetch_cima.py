"""
fetch_cima.py
Rellena products (country_code = 'ES') consultando la API REST pública y
gratuita de CIMA (AEMPS): https://cima.aemps.es/

No requiere API key ni login. Documentación oficial (PDF):
https://www.aemps.gob.es/apps/cima/docs/CIMA_REST_API.pdf

IMPORTANTE — léelo antes de correrlo:
Este entorno de chat no tiene acceso a red, así que este script NO se ha
podido ejecutar ni probar contra la API real todavía. Está escrito según
la documentación pública de CIMA, pero la primera vez que lo corras en tu
máquina (o en Claude Code) es MUY probable que tengamos que ajustar algún
nombre de campo del JSON — eso es normal y es justo la parte de "aprender
haciendo": corre --debug, mira el JSON crudo de una consulta, y ajustamos
juntos el mapeo.

Uso:
    pip install requests
    python fetch_cima.py                # rellena medipass.db
    python fetch_cima.py --debug         # imprime el JSON crudo de la 1ª consulta y sale
"""

import sqlite3
import sys
import time
from datetime import date

import requests

DB_PATH = "medipass.db"
CIMA_BASE = "https://cima.aemps.es/cima/rest"

# Principios activos que ya tenemos en active_ingredients (seed_base.sql).
# El texto de búsqueda es el que se manda a CIMA (parámetro 'practiv1' =
# nombre del principio activo).
INGREDIENTS_TO_FETCH = [
    "docusato sódico",
    "dimenhidrinato",
    "diclofenaco",
    "clorhexidina",
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_ingredient_id(conn, inn_name_prefix):
    """Busca el id en active_ingredients cuyo nombre empiece por el texto dado,
    porque en la BD guardamos 'diclofenaco 1%' pero a CIMA le mandamos 'diclofenaco'."""
    row = conn.execute(
        "SELECT id FROM active_ingredients WHERE inn_name LIKE ? LIMIT 1",
        (f"{inn_name_prefix}%",),
    ).fetchone()
    return row[0] if row else None


def fetch_medicamentos(principio_activo):
    """Llama a GET /medicamentos?practiv1=<principio activo>"""
    resp = requests.get(
        f"{CIMA_BASE}/medicamentos",
        params={"practiv1": principio_activo},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_products(data):
    """Convierte la respuesta cruda de CIMA en tuplas (brand_name, requires_prescription, source_ref).

    OJO: el nombre exacto de los campos (p.ej. si 'receta' viene como
    'receta': true/false o dentro de otra estructura como 'condPresc')
    depende de la versión de la API. Ajusta esta función tras inspeccionar
    la salida real con --debug.
    """
    out = []
    for med in data.get("resultados", []):
        brand_name = med.get("nombre")
        nregistro = med.get("nregistro")
        # Campo más probable según la documentación pública; verificar con --debug.
        requires_rx = med.get("receta")
        if requires_rx is not None:
            requires_rx = 1 if requires_rx else 0
        out.append((brand_name, requires_rx, nregistro))
    return out


def main():
    debug = "--debug" in sys.argv

    if debug:
        sample = fetch_medicamentos(INGREDIENTS_TO_FETCH[0])
        import json

        print(json.dumps(sample, indent=2, ensure_ascii=False)[:4000])
        return

    conn = get_connection()
    total_inserted = 0

    for ingredient in INGREDIENTS_TO_FETCH:
        ingredient_id = get_ingredient_id(conn, ingredient)
        if ingredient_id is None:
            print(f"[aviso] '{ingredient}' no está en active_ingredients, se salta")
            continue

        print(f"Consultando CIMA: {ingredient} ...")
        data = fetch_medicamentos(ingredient)
        products = extract_products(data)

        for brand_name, requires_rx, nregistro in products:
            if not brand_name:
                continue
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO products
                    (active_ingredient_id, country_code, brand_name,
                     requires_prescription, source, source_ref, verified_at)
                VALUES (?, 'ES', ?, ?, 'CIMA_API', ?, ?)
                """,
                (ingredient_id, brand_name, requires_rx, nregistro, date.today().isoformat()),
            )
            total_inserted += cur.rowcount

        conn.commit()
        time.sleep(0.5)  # cortesía con la API pública

    print(f"Listo. Filas afectadas: {total_inserted}")
    conn.close()


if __name__ == "__main__":
    main()
