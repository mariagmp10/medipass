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
| 🇫🇷 Francia | 1.493 | **BDPM (ANSM/data.gouv.fr)** — descarga pública oficial | Real, oficial |
| 🇩🇪🇮🇹🇵🇹🇬🇧 DE/IT/PT/UK | 6 por país | `manual_seed` (escritos a mano, de memoria) | **Sin verificar** — ejemplos para poder probar la app, no para producción |

**España** es el catálogo de CIMA de medicamentos **comercializados y sin
receta** (`comerc=1&receta=0`): 1.066 registros, de los que se guardan 1.014
(52 se omiten porque repiten principio activo y nombre con otro nº de
registro y, para el usuario, serían filas idénticas). Cada producto lleva
forma, dosis, composición, código ATC y grupo terapéutico; 395 tienen foto.

**Francia** es la BDPM filtrada a comercializados, sin ninguna condición de
receta y sin homeopáticos (`fetch_bdpm.py`): 1.512 candidatos, de los que se
guardan 1.493 (19 se omiten por el mismo motivo que en España). Los
homeopáticos se detectan con dos señales (la etiqueta de procedimiento
"Enreg homéo" y que la sustancia diga "préparations homéopathiques"); con
solo la primera se colaron 132 hasta que se comprobó. A diferencia de CIMA:
- La BDPM **no tiene un campo booleano de receta**. Se infiere: un
  medicamento es sin receta si está comercializado y su código CIS **no**
  aparece en el archivo de condiciones de prescripción (`CIS_CPD_bdpm.txt`).
  Verificado con un caso real: Doliprane (paracetamol solo) no aparece ahí;
  Codoliprane (paracetamol + codeína) sí.
- **No tiene foto ni código ATC** en los archivos públicos — esas columnas
  quedan vacías para Francia.
- La forma es texto libre en francés (no una categoría fija como en CIMA).
  Solo se traduce al vocabulario de CIMA para los 4 principios activos que
  ya existían en España (ver `INGREDIENT_MAP`/`FORM_RULES` en
  `fetch_bdpm.py`); el resto de Francia queda con su forma en francés.
- Los archivos vienen en **Windows-1252**, no UTF-8.
- Licencia: reutilización libre citando fuente y fecha, sin alterar los
  datos ([texto de la licencia](https://base-donnees-publique.medicaments.gouv.fr/docs/telechargement/licence_bdpm.pdf)).

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, con su propio formato. La ruta lógica es: dejar el esquema
listo para todos, conectar cada país de verdad, y sustituir cada ejemplo
manual por una fuente real cuando la investiguemos.

**Comparaciones que hoy funcionan con datos reales de dos países** (España +
Francia, mismo principio activo y misma forma):
- Diclofenaco · gel (43 productos entre los dos)
- Diclofenaco · líquido uso tópico
- Clorhexidina · líquido uso tópico (antisépticos de piel; los enjuagues
  bucales franceses quedan aparte, ver abajo)
- Dimenhidrinato · comprimido (España real + el ejemplo manual de Francia,
  porque Francia no tiene ningún comprimido suelto de dimenhidrinato sin
  receta — solo jarabe y cápsula, que son grupos distintos)

Lo que ninguna de las dos fuentes cubre:
- **Docusato sódico**: no comercializado sin receta en España. Francia tiene
  1 producto (un gel), pero España no tiene nada con qué compararlo todavía.
- **Enjuagues/pastillas de garganta con clorhexidina**: en España no existen
  sin receta (son parafarmacia); en Francia sí existen, pero se guardan como
  su propio grupo en francés (p.ej. "clorhexidina · solution pour bain de
  bouche"), sin forzarlos a compararse con los antisépticos de piel.
- **Productos sanitarios y parafarmacia** (apósitos, etc.): ni CIMA ni la
  BDPM son bases de datos de eso.

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
- Para **España y Francia** ya se cumple por construcción: `fetch_cima.py` y
  `fetch_bdpm.py` solo importan medicamentos sin receta, así que la base no
  contiene ningún medicamento real de esos dos países con receta.
- **Todavía no hay campo `legal_category`** en el esquema ni filtro en la app.
- **Productos sanitarios y parafarmacia** no tienen ninguna fuente real
  todavía (ver "Próximos pasos"); solo hay ejemplos manuales.
- Los ejemplos manuales de los países restantes (DE/IT/PT/UK) no están
  verificados y uno de ellos (Voltaren Schmerzgel Forte, Alemania) está
  marcado como "con receta", lo que es un dato de ejemplo, no una fuente.

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
- `seed_manual_non_es.sql` — productos de ejemplo para DE/IT/PT/UK (y los que
  Francia todavía no tiene con qué reemplazar, como los apósitos)
- `fetch_cima.py` — sincroniza España desde CIMA (ver abajo)
- `fetch_bdpm.py` — sincroniza Francia desde la BDPM (ver abajo)
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

## Actualizar los datos de España y Francia

Ambos scripts son sincronizaciones: se pueden ejecutar cuando quieras sin
duplicar nada. Actualizan lo que existe, añaden lo nuevo, borran lo que ya
no cumpla el filtro, y quitan los ejemplos manuales de un país en cuanto
llega un dato real de la misma forma que los sustituye.

```bash
pip install requests

python fetch_cima.py                    # sincroniza y completa el detalle que falte
python fetch_cima.py --no-details       # solo el listado (rápido, sin ATC/composición)
python fetch_cima.py --refresh-details  # vuelve a pedir el detalle de todos (~5 min)
python fetch_cima.py --debug            # imprime el JSON crudo de 1 medicamento

python fetch_bdpm.py                    # sincroniza Francia (descarga ~10 MB cada vez)
python fetch_bdpm.py --debug            # descarga y analiza, sin tocar medipass.db
```

El detalle de CIMA se pide con 4 peticiones en paralelo, por cortesía con la
API pública (unos 5 minutos para ~1.000 productos).

### Construir la base desde cero

```bash
python -c "
import sqlite3
c = sqlite3.connect('medipass.db')
for f in ('schema.sql', 'seed_base.sql', 'seed_manual_non_es.sql'):
    c.executescript(open(f, encoding='utf-8').read())
"
python fetch_cima.py
python fetch_bdpm.py
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

- Los datos de Alemania, Italia, Portugal y Reino Unido son ejemplos sin
  verificar.
- Cada grupo enseña **un** producto por país (el primero por nombre) y cuenta
  los demás; puedes elegir uno concreto buscando su marca.
- La forma de España es la "simplificada" de CIMA (67 valores fijos); la de
  Francia es texto libre en francés, traducido a mano solo para 4 principios
  activos (los que ya existían). Para el resto de Francia, y para todo lo
  demás, una solución cutánea y un enjuague bucal pueden caer en el mismo
  grupo o en grupos que no se comparan cuando deberían.
- Que un medicamento francés sea "sin receta" es una regla **inferida**
  (no aparece en el archivo de condiciones de prescripción), no un campo
  explícito como en CIMA. Se verificó con un caso real, pero no se auditó
  exhaustivamente.
- La dosis de España se muestra tal como la da CIMA, que a veces no indica a
  qué unidad se refiere. Francia no tiene columna de dosis única: se guarda
  solo la composición (nombres de sustancias, sin cantidades).
- Los grupos terapéuticos (ATC) de CIMA vienen sin tildes. Francia no tiene
  ATC ni foto en los archivos que usamos.
- Solo ~39 % de los productos de España tienen foto en CIMA; Francia no
  tiene ninguna.
- La tabla `active_ingredients` mezcla nombres en español (los que ya
  existían) y en francés (los ~540 que trajo la BDPM y no tenían aún
  equivalente en España, de un total de 820) — no hay todavía una capa de
  traducción entre idiomas, solo un mapeo a mano para los 4 principios
  activos compartidos (ver `INGREDIENT_MAP` en `fetch_bdpm.py`).

## Próximos pasos

- Conseguir acceso a **BotPlus/BADIS** o **Medipim** para datos reales de
  parafarmacia y productos sanitarios (hoy no hay ninguna fuente real);
  antes, preguntarles si su licencia permite una app para el público
- Conectar **Reino Unido (MHRA/dm+d)** con una fuente real, sustituyendo su
  ejemplo manual; después Alemania (AMIce/PharmNet.Bund), Italia (AIFA) y
  Portugal (INFARMED), verificando antes cómo acceder a cada una
- Ampliar `INGREDIENT_MAP`/`FORM_RULES` en `fetch_bdpm.py` a más principios
  activos compartidos entre España y Francia, no solo los 4 que ya existían
- Implementar de verdad el `legal_category` y el filtrado descrito en
  "Alcance legal" — hoy solo se cumple para España y Francia por cómo se
  importan, no por un filtro explícito en el esquema
- Desplegar a **Vercel** cuando esté lista para compartir con otras personas
