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

## Estado real de los datos ahora mismo

| País | Fuente | Fiabilidad |
|---|---|---|
| 🇪🇸 España | **CIMA API (AEMPS)** — pública, JSON, sin login | Real, oficial |
| 🇩🇪🇫🇷🇮🇹🇵🇹🇬🇧 DE/FR/IT/PT/UK | `manual_seed` (yo lo escribí a mano) | **Sin verificar** — placeholder para poder probar la app, no para producción |

Esto es intencional: no existe un "CIMA europeo" único. Cada país tiene su
propia agencia, y conectarlas todas de golpe no era realista. La ruta lógica
es: dejar el esquema listo para todos, conectar España de verdad primero, y
sustituir cada país manual por una fuente real cuando la investiguemos.

`medipass.db` ya tiene ~170 productos reales de España para 3 de los 4
principios activos base (dimenhidrinato, diclofenaco 1%, clorhexidina 0,2%).
El cuarto, docusato sódico, no está comercializado en España bajo ese nombre
— CIMA no devuelve resultados para él, y la app lo maneja mostrando "Sin
datos para este país" en vez de romperse.

## Alcance legal

Antes de mostrar esto a usuarios reales, investigamos la Directiva 2001/83/CE
de la UE, que en su artículo 88 prohíbe la publicidad de medicamentos sujetos
a receta médica dirigida al público general. La conclusión: el catálogo de
MediPass, para uso con usuarios reales, debería limitarse a tres categorías:

- **Medicamento sin receta** (OTC)
- **Producto sanitario**
- **Parafarmacia**

y excluir cualquier medicamento con receta del catálogo público.

**Estado actual de la implementación: esto todavía NO está aplicado en el
código.** Hoy la app muestra todos los productos que trae CIMA, con o sin
receta (marcados con la etiqueta correspondiente en la interfaz), y el
buscador no filtra por esta categoría. Aplicar esta restricción de verdad
— añadir un campo `legal_category` al esquema y filtrar por él — queda como
próximo paso antes de pensar en usuarios reales (ver más abajo).

**Esto no es asesoría legal.** Es una interpretación de no-abogados de un
texto normativo. Antes de lanzar esto a usuarios reales hay que consultarlo
con un abogado especializado en derecho farmacéutico/sanitario.

## Arquitectura actual

```
medipass.db  ←── backend/app.py (Flask, puerto 5000)  ←── frontend/ (Vite + React, puerto 5173)
```

- **`backend/app.py`** — expone `GET /api/equivalences` (lee la vista
  `equivalences` de `medipass.db`) y `GET /api/product-detail/<nregistro>`
  (consulta CIMA en vivo para traer dosis, forma farmacéutica y foto real
  del envase — solo funciona para productos de España, que son los únicos
  con número de registro real).
- **`frontend/`** — proyecto Vite + React que reemplaza el prototipo estático
  original. Busca por principio activo o por marca, muestra equivalencias
  entre países, un listado completo de medicamentos en España, y la
  foto/descripción real cuando aplica.
- **`medipass-prototype.jsx`** (en la raíz) — el prototipo original con datos
  de ejemplo en memoria. Ya no se usa; quedó como referencia de diseño.

## Archivos

- `schema.sql` — esquema de la base (tablas + vista `equivalences`)
- `seed_base.sql` — países + principios activos base
- `seed_manual_non_es.sql` — productos placeholder para DE/FR/IT/PT/UK
- `fetch_cima.py` — script real contra la API de CIMA, rellena España
- `medipass.db` — la base ya construida, con España poblado desde CIMA
- `backend/app.py` — servidor Flask (ver arriba)
- `frontend/` — app Vite + React (ver arriba)

## Cómo correr el proyecto

Hacen falta dos terminales, una para el backend y otra para el frontend.

**Terminal 1 — backend:**
```bash
cd backend
pip install flask flask-cors requests
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

### Si necesitas repoblar España desde cero

```bash
pip install requests
python fetch_cima.py --debug   # mira el JSON crudo de una consulta
python fetch_cima.py           # rellena medipass.db de verdad
```

## Consultar la base directamente

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('medipass.db')
for row in conn.execute(\"SELECT * FROM equivalences WHERE inn_name='dimenhidrinato'\"):
    print(row)
"
```

## Próximos pasos

- Conseguir acceso a **BotPlus/BADIS** o **Medipim** para datos reales de
  parafarmacia (hoy no tenemos ninguna fuente real para esa categoría)
- Conectar **Francia (ANSM)** y **Reino Unido (MHRA/dm+d)** con fuentes
  reales, sustituyendo sus placeholders manuales
- Implementar de verdad el `legal_category` y el filtrado descrito en
  "Alcance legal" — hoy es solo una intención documentada, no código
- Investigar fuentes para Italia (AIFA) y Portugal (INFARMED), pendientes
  desde el inicio del proyecto
- Desplegar a **Vercel** cuando esté lista para compartir con otras personas
