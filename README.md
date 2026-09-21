# MediPass · base de datos + app

## Idea del esquema

La tabla puente es `active_ingredients` (el principio activo / DCI), no el
producto. Es lo único que es objetivamente igual entre países — la marca
comercial cambia, el principio activo no. `products` cuelga de ahí, con una
fila por (principio activo, país, marca).

```
countries ──┐
            ├──< products >──── active_ingredients
```

**La unidad de equivalencia es principio activo + forma farmacéutica**, no solo
el principio activo. "Diclofenaco · gel" y "diclofenaco · comprimido" son
grupos distintos: un gel y unas pastillas no son intercambiables. Las
combinaciones también son grupos aparte ("dimenhidrinato" no es lo mismo que
"dimenhidrinato + cafeína"); CIMA ya las distingue.

## Estado real de los datos ahora mismo

| País | Filas | Fuente | Fiabilidad |
|---|---|---|---|
| 🇪🇸 España | 1.014 | **CIMA API (AEMPS)** — pública, JSON, sin login | Real, oficial |
| 🇩🇪🇫🇷🇮🇹🇵🇹🇬🇧 DE/FR/IT/PT/UK | 6 por país | `manual_seed` (escritos a mano, de memoria) | **Sin verificar** — ejemplos para poder probar la app, no para producción |

**España** es el catálogo de CIMA de medicamentos **comercializados y sin
receta** (`comerc=1&receta=0`): 1.066 registros, de los que se guardan 1.014
(52 se omiten porque repiten principio activo y nombre con otro nº de
registro y, para el usuario, serían filas idénticas). Cada producto lleva
forma, dosis, composición, código ATC y grupo terapéutico; 395 tienen foto.

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, y conectarlas todas de golpe no era realista. La ruta lógica
es: dejar el esquema listo para todos, conectar España de verdad primero, y
sustituir cada país manual por una fuente real cuando la investiguemos.

Comparaciones que hoy funcionan de verdad (España + ejemplos de otros países,
misma forma): dimenhidrinato · comprimido y diclofenaco · gel. El resto de
grupos de España existen, pero aún no tienen con qué compararse.

Lo que CIMA **no** cubre:
- **Docusato sódico**: no está comercializado en España (0 resultados).
- **Enjuagues bucales de clorhexidina**: CIMA solo tiene antisépticos
  cutáneos sin receta; los enjuagues son parafarmacia. Por eso los ejemplos
  manuales de clorhexidina no se emparejan con nada de España.
- **Productos sanitarios y parafarmacia** (apósitos, etc.): CIMA es una base
  de medicamentos.

## Alcance legal

Antes de mostrar esto a usuarios reales, investigamos la Directiva 2001/83/CE
de la UE, que en su artículo 88 prohíbe la publicidad de medicamentos sujetos
a receta médica dirigida al público general. La conclusión: el catálogo de
MediPass, para uso con usuarios reales, debería limitarse a tres categorías:

- **Medicamento sin receta** (OTC)
- **Producto sanitario**
- **Parafarmacia**

y excluir cualquier medicamento con receta del catálogo público.

**Estado actual de la implementación, tal como es hoy:**
- Para **España** ya se cumple por construcción: `fetch_cima.py` solo importa
  medicamentos sin receta, así que la base no contiene ningún medicamento
  español con receta.
- **Todavía no hay campo `legal_category`** en el esquema ni filtro en la app.
- **Productos sanitarios y parafarmacia** no tienen ninguna fuente real
  todavía (ver "Próximos pasos"); solo hay ejemplos manuales.
- Los ejemplos manuales de otros países no están verificados y uno de ellos
  (Voltaren Schmerzgel Forte, Alemania) está marcado como "con receta", lo que
  es un dato de ejemplo, no una fuente.

**Esto no es asesoría legal.** Es una interpretación de no-abogados de un
texto normativo. Antes de lanzar esto a usuarios reales hay que consultarlo
con un abogado especializado en derecho farmacéutico/sanitario.

## Arquitectura actual

```
medipass.db  ←── backend/app.py (Flask, puerto 5000)  ←── frontend/ (Vite + React, puerto 5173)
```

- **`backend/app.py`** — expone `GET /api/equivalences`, que devuelve la vista
  `equivalences` de `medipass.db` (todo el catálogo, ~450 KB en JSON). La
  respuesta va comprimida con gzip (~47 KB): además de ahorrar ancho de banda,
  en algunas máquinas Windows las respuestas grandes por localhost se cortan
  a medias y la conexión se cuelga ~19 s.
- **`frontend/`** — proyecto Vite + React. Busca por principio activo, forma o
  marca; compara entre países; muestra foto, composición y dosis del producto
  de España; y ofrece un listado completo de los medicamentos de España.
  Agrupa por principio activo + forma y, como cada país puede tener muchos
  productos por grupo, enseña uno y cuenta cuántos más hay ("y 18 más de esta
  forma en España"). Buscando por una marca concreta se muestra esa marca.
- **`medipass-prototype.jsx`** (en la raíz) — el prototipo original con datos
  de ejemplo en memoria. Ya no se usa; quedó como referencia de diseño.

## Archivos

- `schema.sql` — esquema (tablas + vista `equivalences`); se puede volver a
  ejecutar, recrea la vista
- `seed_base.sql` — países + principios activos base
- `seed_manual_non_es.sql` — productos de ejemplo para DE/FR/IT/PT/UK
- `fetch_cima.py` — sincroniza España desde CIMA (ver abajo)
- `medipass.db` — la base ya construida
- `backend/app.py` — servidor Flask
- `frontend/` — app Vite + React

## Cómo correr el proyecto

Hacen falta dos terminales, una para el backend y otra para el frontend.

**Terminal 1 — backend:**
```bash
cd backend
pip install flask flask-cors
python app.py
```
Queda escuchando en `http://127.0.0.1:5000`.

**Terminal 2 — frontend:**
```bash
cd frontend
npm install
npm run dev
```
Queda escuchando en `http://localhost:5173`.

Con ambos corriendo, abre **`http://localhost:5173`** en el navegador.

## Actualizar los datos de España

`fetch_cima.py` es una sincronización: se puede ejecutar cuando quieras sin
duplicar nada. Actualiza lo que existe, añade lo nuevo y borra los productos
de España de CIMA que ya no cumplan el filtro (retirados, o que pasaron a
requerir receta).

```bash
pip install requests
python fetch_cima.py                    # sincroniza y completa el detalle que falte
python fetch_cima.py --no-details       # solo el listado (rápido, sin ATC/composición)
python fetch_cima.py --refresh-details  # vuelve a pedir el detalle de todos (~5 min)
python fetch_cima.py --debug            # imprime el JSON crudo de 1 medicamento
```

El detalle se pide con 4 peticiones en paralelo, por cortesía con la API
pública (unos 5 minutos para ~1.000 productos).

### Construir la base desde cero

```bash
python -c "
import sqlite3
c = sqlite3.connect('medipass.db')
for f in ('schema.sql', 'seed_base.sql', 'seed_manual_non_es.sql'):
    c.executescript(open(f, encoding='utf-8').read())
"
python fetch_cima.py
```

## Consultar la base directamente

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('medipass.db')
for row in conn.execute(\"SELECT country_code, brand_name, dose, form FROM equivalences WHERE inn_name='dimenhidrinato'\"):
    print(row)
"
```

## Límites conocidos

- Los datos de los otros cinco países son ejemplos sin verificar.
- Cada grupo enseña **un** producto por país (el primero por nombre) y cuenta
  los demás; puedes elegir uno concreto buscando su marca.
- La forma es la "simplificada" de CIMA (67 valores): una solución cutánea y
  un enjuague bucal pueden caer en el mismo grupo, y por eso los ejemplos de
  clorhexidina no se emparejan.
- La dosis se muestra tal como la da CIMA, que a veces no indica a qué
  unidad se refiere.
- Los grupos terapéuticos (ATC) de CIMA vienen sin tildes.
- Solo ~39 % de los productos de España tienen foto en CIMA.

## Próximos pasos

- Conseguir acceso a **BotPlus/BADIS** o **Medipim** para datos reales de
  parafarmacia y productos sanitarios (hoy no hay ninguna fuente real);
  antes, preguntarles si su licencia permite una app para el público
- Conectar **Francia (ANSM, base BDPM)** y **Reino Unido (MHRA/dm+d)** con
  fuentes reales, sustituyendo sus ejemplos manuales; después Alemania, Italia
  (AIFA) y Portugal (INFARMED), verificando antes cómo acceder a cada una
- Implementar de verdad el `legal_category` y el filtrado descrito en
  "Alcance legal" — hoy solo se cumple para España por cómo se importa
- Desplegar a **Vercel** cuando esté lista para compartir con otras personas
