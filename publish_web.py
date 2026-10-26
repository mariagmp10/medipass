"""
publish_web.py
Construye la versión PÚBLICA de MediPass (solo medicamentos sin receta) y la copia a un repositorio aparte,
`medipass-web`, que es el que publica GitHub Pages. Así el repositorio de trabajo (con la base de datos
completa, con recetas) puede ser privado y la web pública no depende de él.

    python publish_web.py              # regenera el catálogo, construye la web, la copia, hace commit y push
    python publish_web.py --no-push    # lo mismo, pero sin subir nada (para revisar antes)

Antes de la primera vez:
  1. Crea en GitHub un repositorio NUEVO, PÚBLICO y VACÍO llamado `medipass-web`.
  2. Clónalo al lado de este proyecto (la carpeta debe llamarse `medipass-web`):
         cd ..   (la carpeta que contiene `medipass`)
         git clone https://github.com/TU_USUARIO/medipass-web.git
  3. En GitHub: medipass-web -> Settings -> Pages -> Source: "Deploy from a branch" -> Branch: main, carpeta / (root).
La web queda en https://TU_USUARIO.github.io/medipass-web/ (tarda un par de minutos en aparecer).

Qué se copia: SOLO el contenido de frontend/dist (la web) más un README con las atribuciones. Se comprueba
antes que el catálogo no tenga recetas ni ejemplos manuales.
"""

import json
import os
import shutil
import subprocess
import sys

import export_static

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "frontend")
DIST = os.path.join(FRONTEND, "dist")
# MEDIPASS_WEB_DIR solo sirve para probar el script contra un repositorio de mentira.
TARGET = os.environ.get("MEDIPASS_WEB_DIR") or os.path.join(os.path.dirname(HERE), "medipass-web")

WEB_README = """# MediPass · versión de prueba

Web estática de MediPass: busca un medicamento sin receta de tu país y encuentra su equivalente en otro.
**Versión de prueba para valoración. Información orientativa: no sustituye el consejo de un farmacéutico o médico.**
Los datos no los ha revisado ningún profesional sanitario.

Solo incluye medicamentos **sin receta** de fuentes oficiales:
- España: CIMA (AEMPS).
- Francia: Base de données publique des médicaments (ANSM).
- Reino Unido: NHS dm+d (NHSBSA). *Contains public sector information licensed under the Open Government Licence v3.0.*

Este repositorio solo contiene la web ya construida; se genera automáticamente desde el proyecto de trabajo.
"""


def run(cmd, cwd, check=True):
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def find_npm():
    found = shutil.which("npm") or shutil.which("npm.cmd")
    if found:
        return found
    for candidate in (r"C:\Program Files\nodejs\npm.cmd", "/usr/local/bin/npm"):
        if os.path.exists(candidate):
            return candidate
    sys.exit("No encuentro npm (Node.js). Instálalo o añádelo al PATH.")


def main():
    push = "--no-push" not in sys.argv
    if not os.path.isdir(os.path.join(TARGET, ".git")):
        sys.exit(
            f"Falta el repositorio {TARGET}\n"
            "Créalo en GitHub (público y vacío, llamado medipass-web) y clónalo ahí; ver la cabecera de este archivo."
        )

    print("1/4 Catálogo público...")
    export_static.main()
    with open(os.path.join(FRONTEND, "public", "equivalences.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    if [r for r in rows if r["requires_prescription"] or r["source"] == "manual_seed"]:
        sys.exit("El catálogo público tiene recetas o ejemplos manuales: no se publica nada.")

    print("2/4 Construyendo la web...")
    run([find_npm(), "run", "build:static"], FRONTEND)

    print("3/4 Copiando a medipass-web...")
    for name in os.listdir(TARGET):
        if name != ".git":
            path = os.path.join(TARGET, name)
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
    for name in os.listdir(DIST):
        src = os.path.join(DIST, name)
        dst = os.path.join(TARGET, name)
        shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
    open(os.path.join(TARGET, ".nojekyll"), "w").close()  # GitHub Pages: no procesar con Jekyll
    with open(os.path.join(TARGET, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(WEB_README)

    print("4/4 Commit...")
    run(["git", "add", "-A"], TARGET)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=TARGET).returncode != 0
    if not changed:
        print("Sin cambios: la web publicada ya está al día.")
        return
    run(["git", "commit", "-m", "Actualizar la versión de prueba (sin recetas)"], TARGET)
    if push:
        run(["git", "branch", "-M", "main"], TARGET)  # GitHub Pages se configura sobre la rama main
        run(["git", "push", "-u", "origin", "main"], TARGET)
        print("Subido. GitHub Pages tarda un par de minutos en actualizar la web.")
    else:
        print(f"Commit hecho en {TARGET}, sin subir (--no-push). Revisa y haz `git push` allí.")


if __name__ == "__main__":
    main()
