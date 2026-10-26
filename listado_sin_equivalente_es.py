"""
listado_sin_equivalente_es.py
Lista los medicamentos de España SIN receta y, para cada uno, si tiene equivalente en Francia, Italia y el
Reino Unido (exacto = mismo principio activo y misma forma; base = mismo principio activo base, otro éster).

    python listado_sin_equivalente_es.py

Escribe sin_equivalente_es.csv (se abre bien con Excel): todos los productos, con una columna por país y
la columna «sin_equivalente_en» con los países donde no hay nada. No cuenta la «forma parecida» (crema/pomada)
de la app, que se decide en el navegador.
"""

import collections
import csv
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sin_equivalente_es.csv")
OTHERS = (("FR", "Francia"), ("IT", "Italia"), ("UK", "Reino Unido"))


def main():
    conn = sqlite3.connect(os.path.join(HERE, "medipass.db"))
    rows = conn.execute(
        """SELECT p.country_code, p.brand_name, ai.inn_name, COALESCE(ai.base_inn, ai.inn_name), p.form,
                  p.requires_prescription, p.legal_category
           FROM products p JOIN active_ingredients ai ON ai.id = p.active_ingredient_id
           WHERE p.source != 'manual_seed'"""
    ).fetchall()
    exact, base = collections.defaultdict(set), collections.defaultdict(set)
    for cc, _brand, inn, b, form, _rx, _legal in rows:
        exact[cc].add((inn, form))
        base[cc].add((b, form))

    out, only_none = [], 0
    for cc, brand, inn, b, form, rx, legal in rows:
        if cc != "ES" or rx:
            continue
        status = {}
        for code, _name in OTHERS:
            if (inn, form) in exact[code]:
                status[code] = "exacto"
            elif (b, form) in base[code] or (inn, form) in base[code]:
                status[code] = "misma base"
            else:
                status[code] = "no"
        missing = [name for code, name in OTHERS if status[code] == "no"]
        only_none += len(missing) == len(OTHERS)
        out.append([brand, inn, form, legal, status["FR"], status["IT"], status["UK"], ", ".join(missing)])
    out.sort(key=lambda r: (-len(r[7].split(", ")) if r[7] else 0, r[1], r[0]))
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["medicamento_espana", "principio_activo", "forma", "estatus_legal", "Francia", "Italia", "Reino Unido", "sin_equivalente_en"])
        w.writerows(out)
    print(f"{len(out)} medicamentos sin receta de España")
    print(f"  sin equivalente en NINGUNO de los tres países: {only_none}")
    for i, (_c, name) in enumerate(OTHERS):
        print(f"  sin equivalente en {name}: {sum(1 for r in out if r[4 + i] == 'no')}")
    print(f"Escrito {OUT}")


if __name__ == "__main__":
    main()
