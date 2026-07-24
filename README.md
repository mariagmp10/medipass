# MediPass · base de datos

## Idea del esquema

La tabla puente es `active_ingredients` (el principio activo / DCI), no el
producto. Es lo único que es objetivamente igual entre países — la marca
comercial cambia, el principio activo no. `products` cuelga de ahí, con una
fila por (principio activo, país, marca).

```
countries ──┐
            ├──< products >──── active_ingredients
```

## Estado real de los datos ahora mismo

| País | Fuente | Fiabilidad |
|---|---|---|
| 🇪🇸 España | **CIMA API (AEMPS)** — pública, JSON, sin login | Real, oficial |
| 🇩🇪🇫🇷🇮🇹🇵🇹🇬🇧 DE/FR/IT/PT/UK | `manual_seed` (yo lo escribí a mano) | **Sin verificar** — placeholder para poder probar la app, no para producción |

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, y conectarlas todas de golpe no era realista. La ruta lógica
es: dejar el esquema listo para todos, conectar España de verdad primero, y
sustituir cada país manual por una fuente real cuando la investiguemos.

Fuentes candidatas para los siguientes países (research pendiente, no
verificado aún):
- 🇫🇷 Francia: ANSM — Base de données publique des médicaments, tiene
  descargas de datos abiertos
- 🇬🇧 Reino Unido: MHRA / dm+d, también datos abiertos
- 🇮🇹 Italia: AIFA
- 🇵🇹 Portugal: INFARMED

## Archivos

- `schema.sql` — esquema de la base (tablas + vista `equivalences`)
- `seed_base.sql` — países + principios activos base
- `seed_manual_non_es.sql` — productos placeholder para DE/FR/IT/PT/UK
- `fetch_cima.py` — script real contra la API de CIMA, rellena España
- `medipass.db` — la base ya construida con schema + seeds (sin CIMA todavía)

## Cómo continuar (necesitas red — usa Claude Code o tu terminal)

```bash
pip install requests

# 1. Mira primero cómo responde CIMA de verdad, para ajustar el mapeo de campos
python fetch_cima.py --debug

# 2. Si el mapeo en extract_products() está bien (o ya lo ajustamos), rellena España
python fetch_cima.py
```

Esto no se ha podido probar contra la API real desde este chat porque el
entorno no tiene acceso a red — es la primera cosa que te recomiendo hacer
en Claude Code: correr `--debug`, pegarme el JSON que devuelve, y ajustamos
juntos `extract_products()` si algún nombre de campo no coincide.

## Consultar la base

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('medipass.db')
for row in conn.execute(\"SELECT * FROM equivalences WHERE inn_name='dimenhidrinato'\"):
    print(row)
"
```

## Conectar esto a la app (MediPass artifact)

El artifact actual usa un array `MEDS` en memoria como si fuera la base de
datos. El siguiente paso natural es montar una API pequeña (Flask/FastAPI)
por encima de `medipass.db` que el artifact pueda llamar — buen segundo
ejercicio de "backend" si quieres seguir aprendiendo por ahí.
