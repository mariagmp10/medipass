"""
export_static.py
Genera el catálogo PÚBLICO que usa la versión estática de la web (la que se publica en internet).

    python export_static.py

Escribe dos archivos en frontend/public/:
    equivalences.json   lo mismo que sirve GET /api/equivalences, pero SOLO con
                        - medicamentos sin receta (requires_prescription = 0), y
                        - datos de fuentes oficiales (se excluyen los ejemplos manuales sin verificar)
    config.json         {"include_prescription": false, "data_dates": {...}}: la web lo lee para adaptar
                        sus textos y citar las fuentes con su fecha (la licencia de la BDPM lo exige)

Por qué sin receta: mostrar marcas de medicamentos con receta al público es lo que se investigó con el
artículo 88 de la Directiva 2001/83/CE (ver README, "Alcance legal"). La versión completa, con recetas,
solo corre en local (backend con INCLUDE_PRESCRIPTION=1).

Hay que volver a ejecutarlo (y hacer commit de los dos archivos) cada vez que cambien los datos; Vercel
vuelve a publicar la web solo al detectar el commit.
"""

import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "medipass.db")
OUT_DIR = os.path.join(HERE, "frontend", "public")

sys.stdout.reconfigure(encoding="utf-8")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM equivalences "
        "WHERE source != 'manual_seed' AND COALESCE(requires_prescription, 0) = 0 "
        "ORDER BY inn_name, form, country_code, brand_name"
    ).fetchall()
    data = [dict(r) for r in rows]
    # Defensa extra: nada con receta ni de ejemplo, pase lo que pase con la consulta.
    assert not [r for r in data if r["requires_prescription"] or r["source"] == "manual_seed"]

    dates = {
        code: date
        for code, date in conn.execute(
            "SELECT country_code, MAX(verified_at) FROM products WHERE source != 'manual_seed' GROUP BY country_code"
        )
    }
    conn.close()

    with open(os.path.join(OUT_DIR, "equivalences.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT_DIR, "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"include_prescription": False, "data_dates": dates}, fh, ensure_ascii=False)

    size = os.path.getsize(os.path.join(OUT_DIR, "equivalences.json"))
    countries = {}
    for r in data:
        countries[r["country_code"]] = countries.get(r["country_code"], 0) + 1
    print(f"equivalences.json: {len(data)} productos sin receta ({size // 1024} KB) {countries}")
    print(f"config.json: fechas de los datos {dates}")


if __name__ == "__main__":
    main()
