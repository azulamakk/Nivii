## 1. Resumen ejecutivo

Para el componente text-to-SQL del sistema, se evaluaron **12 modelos de lenguaje de código abierto** ejecutables localmente a través de [Ollama](https://ollama.com). La evaluación cubre tres niveles de hardware: **estándar (Docker 4 GB)**, **ampliado (Docker 5 GB)** y **avanzado (Docker 8 GB+)**.

El modelo seleccionado **por defecto** es **`qwen2.5-coder:1.5b`** (100% SQL válido, 64.5% correctness, ~1.5 s de latencia, ~986 MB), compatible con cualquier máquina moderna con Docker 4 GB. Para hardware avanzado (Docker 8 GB+), el mejor modelo es **`qwen2.5-coder:7b`** con 80.6% de correctness y 10.5 s de latencia. La evaluación inicial con 5 preguntas simples mostraba a `qwen2.5:1.5b` con 100% de precisión, pero al ampliar la suite a 31 preguntas que incluyen subconsultas, fechas no estándar y agregaciones anidadas, ese modelo cayó al 55% (por debajo del umbral mínimo del 60%), revelando que `qwen2.5-coder:1.5b` es más robusto.

---

## 2. Restricciones del sistema

El requisito central del proyecto es que **el sistema debe correr íntegramente de forma local**, sin depender de APIs externas ni de infraestructura cloud. Esto impone tres restricciones concretas sobre la selección del modelo:

| Restricción | Descripción |
|---|---|
| **Sin GPU dedicada** | El hardware de referencia es una laptop de consumo. Inferencia 100% en CPU. |
| **Memoria limitada** | Docker Desktop asigna por defecto ~4 GB en una Mac con 8 GB de RAM. El modelo debe correr dentro de ese límite. |
| **Portabilidad** | El sistema debe funcionar con `docker compose up --build` en cualquier máquina sin pasos adicionales. |

### Hardware de referencia

- **Mínimo viable:** MacBook Air 2019-2021 Intel, 8 GB RAM, ~256 GB SSD — Docker Desktop ~4 GB
- **Típico:** MacBook Air M1/M2, 8-16 GB RAM — Docker Desktop 4-8 GB
- **No requerido:** GPU dedicada, instancia cloud, memoria >16 GB

> **Nota sobre el entorno de evaluación:** Los benchmarks se ejecutaron con una asignación de Docker de **2.4 GB** (por debajo del estándar). Los modelos que fallaron en esta configuración están documentados en §6 con su requerimiento de memoria real. En una MacBook Air estándar (8 GB / Docker 4 GB), los modelos hasta ~3B parámetros corren sin problemas.

---

## 3. Métricas de evaluación (KPIs)

Se definieron cinco indicadores. Los tres primeros son métricas de **calidad funcional** medibles automáticamente; los dos últimos son **métricas de recursos** que determinan la viabilidad en el hardware de referencia.

---

### KPI 1 — Tasa de SQL ejecutable (`sql_validity_rate`)

**Definición:** Porcentaje de consultas para las cuales el modelo genera un SQL que el motor SQLite ejecuta sin error, en el primer intento.

```
sql_validity_rate = (consultas sin error de sintaxis o ejecución) / (total consultas) × 100
```

**Por qué importa:** Un SQL inválido fuerza reintentos y aumenta la latencia. Un modelo con baja tasa de SQL válido es inutilizable en producción sin lógica de corrección costosa.

**Umbral mínimo aceptable:** ≥ 80%

---

### KPI 2 — Tasa de respuesta correcta (`correctness_rate`)

**Definición:** Porcentaje de consultas cuyo resultado coincide con el *ground truth* pre-computado (ver §4). La verificación es automática comparando el valor, número de filas o nombre de columna retornado contra el valor esperado.

```
correctness_rate = (respuestas con resultado correcto) / (total consultas) × 100
```

**Por qué importa:** Un SQL que ejecuta sin error pero devuelve un resultado incorrecto (e.g., ignora el filtro `WHERE week_day = 'Friday'`) es igualmente inútil. Este KPI captura la comprensión semántica del modelo.

**Umbral mínimo aceptable:** ≥ 60%

---

### KPI 3 — Latencia promedio (`avg_latency_s`)

**Definición:** Tiempo en segundos desde que la petición llega al modelo hasta que devuelve una respuesta completa (sin streaming), promediado sobre todas las consultas con al menos una respuesta generada.

```
avg_latency_s = Σ(tiempo_por_consulta) / n_consultas_respondidas
```

**Por qué importa:** En una laptop sin GPU, la inferencia es CPU-bound. Tiempos >20 s hacen la interfaz inutilizable. El objetivo es mantener la respuesta percibida razonable para el usuario final.

**Umbral máximo aceptable:** ≤ 15 s en el hardware de referencia

---

### KPI 4 — Tasa de reintentos (`avg_retries`)

**Definición:** Número promedio de intentos adicionales (más allá del primero) que el modelo necesita para producir un SQL ejecutable por consulta.

```
avg_retries = Σ(reintentos_por_consulta) / n_consultas
```

**Por qué importa:** Cada reintento duplica la latencia percibida. Un modelo que requiere 1.5 reintentos en promedio triplica el tiempo real. Además, los reintentos consumen contexto y degradan la calidad del feedback.

**Umbral máximo aceptable:** ≤ 0.5

---

### KPI 5 — Memoria requerida

**Definición:** RAM aproximada necesaria para que Ollama cargue el modelo y ejecute inferencia, medida empíricamente o estimada desde el tamaño cuantizado Q4_K_M. Se reporta junto al tamaño del archivo del modelo.

**Por qué importa:** Determina directamente la portabilidad. Un modelo que supera el límite de Docker Desktop en el hardware de referencia no cumple el requisito del sistema, independientemente de su calidad.

| Categoría | RAM requerida | Hardware de referencia |
|---|---|---|
| ✅ Universal | < 2 GB | Funciona en cualquier máquina |
| ⚠️ Estándar | 2 – 4 GB | Requiere 8 GB RAM / 4 GB Docker |
| ❌ Avanzado | 4 – 6 GB | Requiere 16 GB RAM / 6 GB Docker |
| ❌ Especializado | > 6 GB | Requiere GPU o máquina de alto desempeño |

---

## 4. Conjunto de pruebas

Se diseñaron **31 consultas de referencia** en dos idiomas sobre el conjunto de datos `data.csv` (~24 212 registros de transacciones POS). Las consultas cubren tres niveles de dificultad y representan casos de uso reales del sistema.

### Distribución

| Idioma / Dificultad | Simple | Media | Difícil | Total |
|---|---|---|---|---|
| Español (ES) | 4 | 10 | 7 | **21** |
| Inglés (EN) — duplicados semánticos | 2 | 5 | 3 | **10** |
| **Total** | **6** | **15** | **10** | **31** |

Los duplicados en inglés comparten el mismo `reference_sql` que su par en español, lo que permite comparar directamente el rendimiento del modelo según el idioma de la pregunta.

### Ejemplos representativos por dificultad

| Nivel | Ejemplo | Patrón SQL |
|---|---|---|
| Simple | ¿Cuántos registros hay en total? | `COUNT(*)` |
| Simple | ¿Cuántos mozos distintos hay? | `COUNT(DISTINCT waiter)` |
| Media | ¿Cuál es el producto más comprado los viernes? | `WHERE` + `GROUP BY` + `LIMIT 1` |
| Media | ¿Cuáles son los 5 productos con mayor ingreso total? | `SUM` + `GROUP BY` + `LIMIT 5` |
| Difícil | ¿Qué productos tienen cantidad total superior al promedio? | `HAVING` + subconsulta anidada |
| Difícil | ¿Cuál es el mozo con mayor ingreso promedio por ticket? | Subconsulta de dos niveles |
| Difícil | ¿En qué mes se registró el mayor ingreso total? | `SUBSTR`/`INSTR` sobre formato `M/D/YYYY` |
| Difícil | ¿Cuánto generó cada mozo en octubre de 2024? | Filtro de fecha con `LIKE` sobre formato no estándar |

### Framework de evaluación

En vez de valores esperados hardcodeados, cada pregunta lleva un campo `reference_sql`. En tiempo de evaluación:

1. Se ejecuta `reference_sql` contra la base de datos → resultado de referencia.
2. Se ejecuta el SQL generado por el modelo → resultado del modelo.
3. Se comparan ambos conjuntos con `results_match()`: normaliza valores numéricos a 4 decimales, ignora mayúsculas, ordena los valores dentro de cada fila (insensible al alias de columna) y opcionalmente ordena las filas (insensible al `ORDER BY` cuando el orden no es semánticamente relevante).

El script de evaluación se encuentra en `eval/benchmark.py` y puede reproducirse con:

```bash
python3 eval/benchmark.py                  # todos los modelos
python3 eval/benchmark.py qwen2.5-coder:1.5b  # modelo específico
```

---

## 5. Modelos evaluados

### 5a. Modelos con benchmark completo — entorno estándar (Docker 4 GB)

Todos ejecutados vía Ollama con cuantización Q4_K_M sobre CPU.

| Modelo | Organización | Parámetros | Tamaño archivo | RAM estimada | Enfoque |
|---|---|---|---|---|---|
| `qwen2.5-coder:0.5b` | Alibaba | 0.5 B | 313 MB | ~0.5 GB | Código |
| `qwen2.5-coder:1.5b` | Alibaba | 1.5 B | 986 MB | ~1.2 GB | Código |
| `qwen2.5:1.5b` | Alibaba | 1.5 B | 986 MB | ~1.2 GB | General (instruct) |
| `llama3.2:1b` | Meta | 1.2 B | 1.3 GB | ~1.5 GB | General |
| `deepseek-coder:1.3b` | DeepSeek AI | 1.3 B | 776 MB | ~1.0 GB | Código |

### 5b. Modelos con benchmark completo — hardware ampliado (Docker 5 GB)

| Modelo | Organización | Parámetros | Tamaño archivo | RAM estimada | Enfoque |
|---|---|---|---|---|---|
| `llama3.2:3b` | Meta | 3.2 B | 2.0 GB | ~2.0 GB | General |
| `gemma2:2b` | Google | 2.6 B | 1.6 GB | ~2.5 GB | General |
| `gemma3:4b` | Google | 4 B | 3.3 GB | ~4.0 GB | General (requiere num_ctx cap) |
| `qwen3.5:2b` | Alibaba | 2 B | 2.7 GB | ~4.0 GB | General (requiere num_ctx cap) |

### 5c. Modelos descartados — no evaluables

| Modelo | Organización | Parámetros | Tamaño archivo | Problema | Notas |
|---|---|---|---|---|---|
| `qwen3.5:4b` | Alibaba | 4 B | 3.4 GB | Latencia extrema | >150 s/consulta incluso con think=false; cuelgues indefinidos en queries hard |
| `sqlcoder:7b` | Defog AI | 7 B | 4.1 GB | Prompt incompatible‡ | Requiere ≥ 6 GB RAM |

> ‡ `sqlcoder:7b` está disponible en Ollama pero requiere un template de prompt específico (`### Task / ### Database Schema / ### Answer`) distinto al formato instruct estándar que usa este sistema. Con el prompt actual genera texto explicativo en vez de SQL. Sería necesario un path de prompt dedicado en el benchmark para evaluarlo correctamente.

### 5d. Modelos evaluados — tier 8 GB Docker

| Modelo | Organización | Parámetros | Tamaño archivo | RAM estimada | Enfoque |
|---|---|---|---|---|---|
| `qwen2.5-coder:7b` | Alibaba | 7.6 B | 4.7 GB | ~5.5 GB | Código/SQL (fine-tuned) |
| `gemma4:e2b` | Google | ~4 B (cuantizado) | 3.7 GB | ~7.2 GB | General |

---

## 6. Resultados del benchmark

Suite ampliada de **31 preguntas** (21 ES + 10 EN) en 3 niveles de dificultad. Métricas adicionales: `ES%` (correctas en español) y `EN%` (correctas en inglés).

### 6a. Tabla comparativa — todos los modelos evaluados

| Modelo | SQL% | OK% | ES% | EN% | Lat avg | Reintentos | RAM | Veredicto |
|---|---|---|---|---|---|---|---|---|
| **`qwen2.5-coder:7b`**¶ | 96.8% | **80.6%** | **85.7%** | 70.0% | 10.5 s | 0.16 | ❌ ~5.5 GB | ⭐ Elegido (Docker 8 GB) |
| `gemma3:4b`† | 100% | **74.2%** | **71.4%** | **80.0%** | 3.1 s | 0.00 | ⚠️ ~4.0 GB | ⭐ Elegido (Docker 5 GB) |
| `gemma4:e2b`¶ | 100% | 71.0% | 66.7% | **80.0%** | 15.1 s | 0.00 | ❌ ~7.2 GB | 8 GB, bueno en inglés |
| `qwen3.5:2b`† | 96.8% | 67.7% | 66.7% | 70.0% | 28.4 s | 0.13 | ⚠️ ~4.0 GB | Latencia inaceptable (think=false) |
| **`qwen2.5-coder:1.5b`** | **100%** | 64.5% | 66.7% | 60.0% | **1.5 s** | **0.10** | ✅ ~1.2 GB | ⭐ Elegido (Docker 4 GB) |
| `llama3.2:3b` | 100% | 64.5% | 61.9% | 70.0% | 2.4 s | 0.16 | ✅ ~2.0 GB | Bueno (más RAM) |
| `qwen2.5:1.5b` | 100% | 54.8% | 61.9% | 40.0% | 1.6 s | 0.00 | ✅ ~1.2 GB | Por debajo del umbral |
| `llama3.2:1b` | 96.8% | 41.9% | 33.3% | 60.0% | 1.6 s | 0.29 | ✅ ~1.5 GB | Insuficiente |
| `gemma2:2b` | 93.5% | 38.7% | 33.3% | 50.0% | 2.8 s | 0.23 | ✅ ~2.5 GB | Insuficiente |
| `qwen2.5-coder:0.5b` | 93.5% | 32.3% | 23.8% | 50.0% | 0.7 s | 0.19 | ✅ ~0.5 GB | Ultra-rápido/limitado |
| `gemma3:1b` | 61.3% | 32.3% | 28.6% | 40.0% | 1.3 s | 1.32 | ✅ ~1.0 GB | Por debajo de umbral |
| `deepseek-coder:1.3b` | 0% | 0% | 0% | 0% | — | — | ✅ ~1.0 GB | Error 500‡ |
| `qwen3.5:4b` | N/A | — | — | — | — | — | ❌ >5 GB | Latencia extrema (>150 s/q)∥ |
| `sqlcoder:7b` | N/A | — | — | — | — | — | ❌ ~5 GB | Prompt incompatible§ |

> † `gemma3:4b` y `qwen3.5:2b` requieren `num_ctx=4096` para caber en Docker 5 GB. Sin ese cap, Ollama pre-asigna KV cache para contextos de 32K–128K tokens que superan el límite. Con el cap, la calidad no se ve afectada: nuestros prompts son ~350 tokens en el peor caso.

> ‡ `deepseek-coder:1.3b` pasa el chequeo de disponibilidad pero retorna HTTP 500 en generación real — posible presión de memoria que no se manifiesta hasta la inferencia efectiva.

> § `sqlcoder:7b` usa un template `### Task / ### Database Schema / ### Answer` incompatible con el prompt instruct estándar del sistema. Evaluado manualmente: genera texto explicativo en vez de SQL con el prompt actual.

> ¶ `qwen2.5-coder:7b` y `gemma4:e2b` requieren Docker 8 GB (≥7 GB RAM disponible para Ollama). No aptos para el hardware de referencia estándar (Docker 4 GB).

> ∥ `qwen3.5:4b` produce cuelgues indefinidos en consultas complejas incluso con `think=false`. Descartado por latencia e inestabilidad.

---

### 6b. Análisis por modelo

#### `qwen2.5-coder:1.5b` — Ganador empírico (suite ampliada)

Mejor modelo para el hardware de referencia: **100% SQL válido, 64.5% correcto, 1.5 s de latencia**. Supera a su variante instruct general (`qwen2.5:1.5b`) en la suite ampliada, particularmente en consultas de agrupación compleja y subconsultas. La especialización en código resulta ventajosa cuando las consultas son más difíciles. Empate exacto con `llama3.2:3b` en correctness pero con la mitad de RAM, lo que lo hace superior para el hardware de referencia.

#### `llama3.2:3b` — Alternativa para hardware con más memoria

Empata con `qwen2.5-coder:1.5b` en correctness global (64.5%) pero **lidera en inglés (70% vs 60%)**. Requiere ~2 GB RAM (vs ~1.2 GB). Recomendado para máquinas con Docker ≥ 4 GB y carga de trabajo con preguntas predominantemente en inglés.

#### `qwen2.5:1.5b` — Superado por la suite ampliada

Ganador de la evaluación inicial (5 preguntas, 100%). Al ampliar a 31 preguntas con dificultad real, cayó al **54.8%** — por debajo del umbral mínimo del 60%. Falla especialmente en inglés (40%) y en consultas difíciles. El fine-tuning instruct general es menos robusto que el orientado a código para consultas SQL complejas.

#### `llama3.2:1b` y `gemma2:2b` — Insuficientes

Ambos por debajo del 60% de correctness. `llama3.2:1b` es rápido pero impreciso en español (33.3%). `gemma2:2b` muestra mayor latencia que `llama3.2:3b` con peores resultados.

#### `qwen2.5-coder:0.5b` — Ultra-rápido para entornos restringidos

32.3% de correctness — muy por debajo del umbral. Sin embargo, su latencia de 0.7 s y consumo de ~0.5 GB lo hacen la única opción viable en hardware con menos de 1 GB de RAM disponible para el modelo.

#### `gemma3:4b` — Mejor modelo general (Docker 5 GB)

Con `num_ctx=4096`, corre dentro del límite de 5 GB Docker y alcanza **74.2% de correctness** — el mejor resultado de toda la evaluación. Destaca especialmente en inglés (80%) y en consultas medias (86.7%). Latencia de 3.1 s y cero reintentos. Requiere Docker ≥ 5 GB; no apto para el hardware de referencia estándar (4 GB). Es la recomendación para usuarios con Docker 5 GB+.

#### `qwen3.5:2b` — Descartado por latencia

Evaluado en dos modos: con thinking (por defecto) y con `think=false` vía Ollama options.

| Modo | SQL% | Correcto | ES% | EN% | Latencia |
|---|---|---|---|---|---|
| `think=true` (defecto) | 100% | 64.5% | 71.4% | 50.0% | 32.0 s |
| `think=false` | 96.8% | 67.7% | 66.7% | 70.0% | 28.4 s |

Deshabilitar el pensamiento mejora ligeramente la correctness (+3.2 pp) y la latencia (−3.6 s), pero **28.4 s sigue siendo inaceptable** para una interfaz interactiva. La lentitud no proviene del razonamiento interno sino de la inferencia CPU del modelo en sí — la arquitectura Qwen3.5 es más lenta que Gemma3 a tamaño equivalente en este hardware.

#### `qwen2.5-coder:7b` — Mejor modelo general (Docker 8 GB)

Con 7.6 B parámetros y fine-tuning orientado a código, `qwen2.5-coder:7b` alcanza **80.6% de correctness** — el mejor resultado de toda la evaluación. Destaca especialmente en español (85.7%), siendo el único modelo que supera el 80% de correctness global. Logró 100% en preguntas simples y medias; las fallas se concentran en consultas con fechas de formato no estándar (Q18, Q18b) y subconsultas de dos niveles (Q15). Latencia promedio de 10.5 s, con picos de 30–45 s en consultas complejas. Requiere Docker 8 GB (~5.5 GB RAM). Es la recomendación para usuarios con hardware ampliado.

#### `gemma4:e2b` — Segunda opción (Docker 8 GB)

`gemma4:e2b` alcanza **71.0% de correctness** con 100% de SQL válido y cero reintentos — robusto en generación de SQL sintácticamente correcto. Destaca en inglés (80%) e impresiona en consultas medias (80%), pero falla en consultas difíciles que involucran fechas con formato no estándar (Q18, Q19) y promedios por mozo (Q17). Su latencia promedio de 15.1 s es la más alta de todos los modelos evaluados, siendo su principal desventaja frente a `qwen2.5-coder:7b`.

#### `gemma3:1b` — Descartado

61% de SQL válido (por debajo del umbral del 80%) y 32% de correctness, con 1.32 reintentos en promedio. La alta tasa de reintentos indica que el modelo genera frecuentemente SQL con errores de sintaxis o estructura. Siendo el único modelo Gemma3 ejecutable en el hardware de referencia, no aporta ninguna ventaja sobre modelos equivalentes de la familia Qwen2.5.

#### `deepseek-coder:1.3b` — Descartado

0% de SQL válido — HTTP 500 en todas las consultas. Comportamiento consistente con OOM diferido o corrupción del estado del modelo bajo carga de generación.

---

### 6c. Rendimiento por nivel de dificultad

| Modelo | Simple (6q) | Media (15q) | Difícil (10q) |
|---|---|---|---|
| `qwen2.5-coder:7b`¶ | **100%** | **100%** | **50.0%** |
| `gemma3:4b`† | **100%** | **86.7%** | 30.0% |
| `gemma4:e2b`¶ | 100% | 80.0% | 40.0% |
| `qwen2.5-coder:1.5b` | 100% | 86.7% | 20.0% |
| `llama3.2:3b` | 100% | 80.0% | 20.0% |
| `qwen3.5:2b`† | 100% | 73.3% | 20.0% |
| `qwen2.5:1.5b` | 83.3% | 73.3% | 10.0% |
| `llama3.2:1b` | 83.3% | 46.7% | 10.0% |
| `gemma2:2b` | 66.7% | 53.3% | 0.0% |
| `qwen2.5-coder:0.5b` | 83.3% | 33.3% | 0.0% |
| `gemma3:1b` | 66.7% | 26.7% | 0.0% |

Las preguntas difíciles (subconsultas, fechas no estándar, agregaciones de dos niveles) exponen una brecha clara. `qwen2.5-coder:7b` es el único modelo que supera el 40% en ese nivel (50%), gracias a su fine-tuning específico en código. Los modelos de 1–4B parámetros se quedan en el 20–40%.

![Difficulty breakdown](eval/charts/difficulty_breakdown.png)

**Correctness por idioma** — `gemma3:4b` lidera en inglés (80%); la mayoría de modelos rinden mejor en español:

![Language split](eval/charts/language_split.png)

> Los gráficos se generan con `python3 eval/charts.py` (requiere `pip install -r eval/requirements.txt`).

---

## 7. Análisis de trade-offs

### Velocidad vs. precisión (suite ampliada, 31 preguntas)

El siguiente gráfico resume el trade-off central: eje X = latencia promedio (escala logarítmica), eje Y = correctness. Verde = hardware estándar (Docker ≤ 4 GB); naranja = hardware ampliado (5 GB); morado = avanzado (8 GB). El tamaño de cada burbuja es proporcional a la tasa de SQL válido.

![Correctness vs Latency](eval/charts/correctness_vs_latency.png)

`qwen2.5-coder:7b` lidera en la esquina superior con 80.6% de correctness a 10.5 s. `gemma3:4b` ocupa la zona ideal de balance (74.2%, 3.1 s) pero exige 5 GB Docker. `qwen2.5-coder:1.5b` domina en la franja sub-2 s para hardware estándar. `qwen3.5:2b` y `gemma4:e2b` quedan desplazados a la derecha por latencia elevada.

La correlación entre tamaño y precisión se confirma en la suite ampliada, pero con matices: `qwen2.5:1.5b` (instruct general) es superado por `qwen2.5-coder:1.5b` (orientado a código) en consultas complejas — el fine-tuning SQL hace diferencia a partir de Q15 en adelante.

### Portabilidad vs. calidad

| Escenario | Modelo recomendado | Correctness | RAM |
|---|---|---|---|
| Mínimo (Docker < 2 GB) | `qwen2.5-coder:0.5b` | 32% | ~0.5 GB |
| Estándar (Docker 4 GB) | **`qwen2.5-coder:1.5b`** | **64.5%** | ~1.2 GB |
| Ampliado (Docker 5 GB) | **`gemma3:4b`** | **74.2%** (EN 80%) | ~4.0 GB |
| Avanzado (Docker 8 GB) | **`qwen2.5-coder:7b`** | **80.6%** (ES 85.7%) | ~5.5 GB |

### ¿Por qué no un modelo más grande?

`sqlcoder:7b` (el único 7B especializado en SQL disponible en Ollama) tiene un formato de prompt incompatible con el sistema actual. Modelos de 13B+ parámetros en CPU requieren >60 s por consulta — inaceptable para una interfaz interactiva.

`qwen2.5-coder:7b` es el límite práctico para inferencia CPU: 10.5 s de latencia promedio con 80.6% de correctness. Para el hardware de referencia (Docker 4 GB), el sweet spot sigue siendo `qwen2.5-coder:1.5b`; el tier 8 GB es una opción para máquinas con más recursos.

---

## 8. Modelos seleccionados

### SQL model: `gemma3:4b` (Docker 5 GB)

| Criterio | Valor | Cumple umbral |
|---|---|---|
| Tasa SQL válido | 100% | ✅ (≥ 80%) |
| Tasa respuesta correcta | 74.2% | ✅ (≥ 60%) |
| Latencia promedio | 3.1 s | ✅ (≤ 15 s) |
| Reintentos promedio | 0.00 | ✅ (≤ 0.5) |
| RAM requerida | ~4.0 GB | ✅ Docker 5 GB |

`gemma3:4b` es el mejor modelo por correctness que corre dentro de un límite de memoria razonable (5 GB Docker). Requiere `num_ctx=4096` para caber en ese límite (ya configurado en el código).

### NL model: `qwen2.5-coder:1.5b`

El modelo de respuesta en lenguaje natural se mantiene en `qwen2.5-coder:1.5b`: es rápido (1.5 s), ya está descargado como fallback del SQL model, y la tarea de parafrasear un resultado tabulado es menos exigente que generar SQL correcto. Usar el mismo modelo 4B para ambas tareas consumiría ~8 GB RAM adicionales sin ganancia apreciable en la calidad de la respuesta en prosa.

### Por qué no `qwen2.5-coder:7b` como SQL model

`qwen2.5-coder:7b` alcanza 80.6% de correctness (+6.4 pp sobre `gemma3:4b`) pero su latencia de **10.5 s promedio** es 3.4× mayor que `gemma3:4b` (3.1 s). Además requiere Docker 8 GB (~5.5 GB RAM), lo que eleva el requisito de hardware sin que la ganancia de precisión lo justifique para el caso de uso interactivo. La mejora de 6 pp no compensa triplicar la latencia y doblar el requerimiento de memoria.

### Por qué no `qwen2.5-coder:1.5b` como SQL model (modelo anterior)

En la evaluación inicial (5 preguntas simples/medias), `qwen2.5-coder:1.5b` obtuvo 100% y era el mejor dentro de 4 GB Docker. Con la suite ampliada a 31 preguntas, `gemma3:4b` lo supera en 9.7 pp (74.2% vs 64.5%) con latencia comparable (3.1 s vs 1.5 s) y cero reintentos. El trade-off de requerir 5 GB Docker a cambio de casi 10 pp de correctness es favorable.

### Por qué no `qwen2.5:1.5b` (modelo original)

En la evaluación inicial (5 preguntas simples/medias), `qwen2.5:1.5b` obtuvo 100% de precisión y fue seleccionado. Al ampliar la suite a 31 preguntas con dificultad real, cayó al **54.8%** — por debajo del umbral mínimo del 60%. Falla especialmente en inglés (40%) y en consultas con subconsultas o agrupaciones complejas. La hipótesis anterior ("el fine-tuning de código reduce la flexibilidad") se invierte con consultas más exigentes: el fine-tuning orientado a código es una ventaja, no una limitación.

### Estrategias de mitigación para las limitaciones del modelo

Se implementan las siguientes estrategias para maximizar la fiabilidad:

1. **Inyección de esquema completo** en cada prompt de sistema — el modelo no necesita "recordar" la estructura de la tabla.
2. **Few-shot examples** con 3 ejemplos de pares pregunta→SQL en el prompt, anclan el formato de salida.
3. **Bucle de corrección con retroalimentación** — si el SQL falla, el error de SQLite se incluye en el prompt del siguiente intento (hasta 3 reintentos).
4. **Limpieza de output** — el código elimina markdown fences, texto explicativo y puntuación residual antes de ejecutar el SQL.

---

## 9. Modelos considerados pero no evaluados

Los siguientes modelos fueron investigados durante el proceso de selección pero **no pudieron ser evaluados con métricas completas** debido a restricciones de hardware o a no ser ejecutables localmente en el hardware de referencia.

### 9a. Requieren hardware por encima del referencia

Estos modelos son de código abierto y ejecutables localmente vía Ollama, pero su requerimiento de memoria los excluye del hardware de referencia (MacBook Air 8 GB / Docker 4 GB).

| Modelo | Parámetros | RAM estimada | Motivo de exclusión |
|---|---|---|---|
| `llama3.2:3b` | 3.2 B | ~3.0 GB | Requiere ≥8 GB RAM / 4 GB Docker. OOM en entorno restringido. |
| `gemma2:2b` (Google) | 2.6 B | ~2.5 GB | Borderline en referencia estándar. OOM en entorno restringido. |
| `codellama:7b` (Meta) | 7 B | ~5.0 GB | Mismo problema de memoria que qwen2.5-coder:7b. |
| `mistral:7b` (Mistral AI) | 7 B | ~5.0 GB | Modelo de propósito general; requiere 16 GB RAM. |
| `starcoder2:3b` (BigCode) | 3 B | ~2.5 GB | Especializado en código; requiere ≥4 GB Docker. |
| `phi3:mini` (Microsoft) | 3.8 B | ~2.8 GB | Requiere ≥4 GB Docker para inferencia estable. |
| `phi3.5:mini` (Microsoft) | 3.8 B | ~2.8 GB | Misma restricción que phi3:mini. |

### 9b. Disponibles solo como API (no ejecutables localmente)

Estos modelos ofrecen calidad superior pero **violan el requisito fundamental** del proyecto: deben ejecutarse íntegramente en la máquina del usuario sin conexión a servicios externos.

| Modelo | Proveedor | Motivo de exclusión |
|---|---|---|
| GPT-4o / GPT-4-turbo | OpenAI | API propietaria. Requiere conexión y clave de pago. |
| GPT-3.5-turbo | OpenAI | API propietaria. Costos por token. |
| Claude 3.5 Sonnet / Haiku | Anthropic | API propietaria. Requiere clave de API. |
| Gemini Pro / Flash | Google | API propietaria. Requiere cuenta y clave. |
| Gemini 2.0 Flash | Google | Mismo problema que Gemini Pro. |
| Mixtral 8x7B (API) | Mistral AI | Disponible como API; versión local requiere ~90 GB RAM. |

> Nota del asignamiento: se permite incluir una API como funcionalidad extra de comparación, pero el modelo hosteado localmente debe ser el caso principal.

### 9c. Solo disponibles vía HuggingFace (sin soporte nativo en Ollama)

Estos modelos requieren un pipeline de inferencia personalizado con `transformers` + `torch`, lo que añade complejidad al Dockerfile (imagen base pesada con CUDA/CPU) y no es compatible con la arquitectura del sistema.

| Modelo | Organización | Parámetros | Observación |
|---|---|---|---|
| `defog/sqlcoder-7b-2` | Defog AI | 7 B | Especializado en SQL, excelente calidad. Requiere GPU (14 GB VRAM) o inferencia muy lenta en CPU. |
| `defog/sqlcoder-34b` | Defog AI | 34 B | Calidad máxima para SQL. Inviable en hardware de consumo. |
| `NumbersStation/nsql-350M` | NumbersStation | 350 M | Pequeño y rápido, pero con HuggingFace + transformers. Sin soporte Ollama. |
| `NumbersStation/nsql-6B` | NumbersStation | 6 B | Misma restricción de infraestructura + requiere GPU. |
| `mrm8488/t5-base-finetuned-wikiSQL` | HuggingFace community | 250 M | Muy pequeño. Solo fine-tuned en WikiSQL, no generaliza bien a esquemas arbitrarios. |
| `cssupport/t5-small-awesome-text-to-sql` | HuggingFace community | 60 M | Ultra pequeño. Calidad muy baja en consultas fuera de WikiSQL. |
| `tscholak/3vnuv1vf` (Picard) | Salesforce | 3 B | Sistema de decodificación constrained interesante, pero requiere infraestructura propia. |
| `starcoder2-15b` | BigCode | 15 B | Orientado a código, sin fine-tuning SQL específico. Requiere GPU. |

---

## 10. Investigación de frameworks: LangChain / LangGraph

Durante el desarrollo se evaluó la posibilidad de reemplazar la capa de integración con el LLM usando **LangChain** y su componente `create_sql_agent`, en lugar de llamadas directas a la API REST de Ollama.

### ¿Qué ofrece LangChain para este caso de uso?

LangChain provee:

- **`ChatOllama` / `OllamaLLM`**: abstracción sobre las llamadas HTTP a Ollama, reemplazando `ollama_client.py`.
- **`SQLDatabaseChain`** (deprecado en v0.2) / **`create_sql_agent`**: pipeline pre-construido que inyecta el esquema, genera SQL, lo ejecuta y produce una respuesta en lenguaje natural — equivalente a `text_to_sql.py` + `nl_response.py` en un solo objeto.
- **`ChatPromptTemplate`**: gestión de prompts estructurada en lugar de f-strings.
- **LangSmith**: trazabilidad y observabilidad integradas, útil para depurar la calidad de los prompts.

`create_sql_agent` va más allá de un pipeline fijo: entrega al LLM un conjunto de **herramientas** (`sql_db_list_tables`, `sql_db_schema`, `sql_db_query`, `sql_db_query_checker`) y le permite decidir cuáles usar en cada paso. Esto habilita razonamiento en múltiples pasos — por ejemplo, consultar primero los nombres de columnas y luego formular la query — y auto-corrección con re-lectura del esquema ante errores.

### Por qué se decidió no utilizarlo

| Razón | Detalle |
|---|---|
| **Overhead de dependencias** | LangChain añade ~40 dependencias transitivas. El `requirements.txt` actual tiene 5 paquetes. El tamaño de la imagen Docker aumentaría considerablemente. |
| **Inestabilidad de la API** | LangChain ha tenido 2–3 reestructuraciones mayores en 2 años (v0.1 → v0.2 → v0.3). `SQLDatabaseChain` fue deprecado y reemplazado por `create_sql_agent` en ciclos cortos. Esto introduce riesgo de rotura en el futuro. |
| **Latencia adicional por agente** | `create_sql_agent` realiza múltiples llamadas al LLM por pregunta (descubrimiento de tablas, lectura de esquema, generación de SQL, verificación). En un modelo 1.5B con ~2.5 s por llamada, una pregunta simple puede tardar 10–15 s en vez de 2.5 s. |
| **Complejidad innecesaria** | El flujo actual es lineal: `pregunta → SQL → ejecutar → respuesta NL`. El bucle de reintentos tiene ~20 líneas. No hay ramificación compleja que justifique un grafo de estados. |
| **Sin beneficio funcional observable** | Para una tabla única con consultas analíticas directas, el agente no aporta capacidad adicional respecto al pipeline manual con few-shot prompting. |

### Cuándo sería una opción válida

LangChain / LangGraph se vuelve una elección razonable si el sistema evoluciona hacia:

- **Múltiples tablas con JOINs complejos**: el agente puede explorar el esquema dinámicamente en vez de inyectarlo completo en el prompt.
- **Razonamiento en múltiples pasos**: preguntas que requieren consultas intermedias (e.g., "¿El producto más vendido en el mes con mayor ingreso?").
- **Flujos con aprobación humana**: LangGraph permite pausar el grafo y esperar confirmación antes de ejecutar queries destructivas.
- **Observabilidad en producción**: LangSmith ofrece trazas detalladas de cada paso del pipeline, útil para detectar regresiones en la calidad del modelo.
- **Múltiples herramientas heterogéneas**: si el sistema necesita combinar SQL con búsqueda vectorial, APIs externas o documentos, la abstracción de herramientas de LangChain es valiosa.

En el estado actual del proyecto, el costo supera el beneficio. La implementación directa es más liviana, más predecible y más fácil de mantener.

---

## 11. Alternativa considerada: inferencia directa con HuggingFace Transformers

Se evaluó la posibilidad de reemplazar Ollama con inferencia directa usando la librería `transformers` de HuggingFace dentro del contenedor de la aplicación.

### Qué ofrecería este enfoque

- **Contenedor único**: elimina el servicio `ollama` de docker-compose; el modelo se carga en el mismo proceso Python que FastAPI.
- **Acceso a modelos exclusivos de HuggingFace**: modelos SQL-especializados como `defog/sqlcoder-7b-2` o `NumbersStation/nsql-350M` no están disponibles en Ollama y solo se pueden usar vía `transformers`.
- **Control fino sobre el pipeline de inferencia**: acceso directo a logits, embeddings, parámetros de sampling, tokenización personalizada.

### Por qué se descartó

| Razón | Detalle |
|---|---|
| **Imagen Docker +2–3 GB** | `torch` (CPU) pesa ~2.5 GB solo en dependencias. La imagen actual es ~400 MB total. |
| **Inferencia CPU más lenta** | Ollama usa llama.cpp internamente, que está altamente optimizado para CPU mediante GGUF y rutinas BLAS. PyTorch en CPU es considerablemente más lento para inferencia de transformers. |
| **Gestión de cuantización manual** | Ollama aplica Q4_K_M automáticamente. Con `transformers` se necesita `bitsandbytes` para cuantización en 4-bit/8-bit, o un loader GGUF separado (`llama-cpp-python`), añadiendo complejidad al Dockerfile. |
| **Riesgo de crash total** | Si el modelo OOM dentro del proceso de FastAPI, la aplicación completa cae. Con Ollama en contenedor separado, un OOM solo afecta al servicio de modelos; la app puede responder con un error controlado. |
| **Caché de modelos más compleja** | Ollama gestiona la caché con un volumen Docker (`ollama_data`). Con `transformers`, se necesita gestionar el directorio de caché de HuggingFace (`~/.cache/huggingface`) mediante un volumen separado para evitar re-descargas en cada `docker compose up`. |

### Cuándo sería una opción válida

- Si se necesita un modelo disponible solo en HuggingFace (e.g., `defog/sqlcoder`) que no tiene equivalente en Ollama.
- Si se requiere fine-tuning o acceso a representaciones internas del modelo (embeddings por capa, logits, atención).
- Si el entorno de despliegue ya tiene `torch` instalado por otras razones, absorbiendo el costo de la dependencia.

---

## 12. Alternativa considerada: aceleración por GPU en Apple Silicon (Metal / MPS)

Se investigó si era posible aprovechar los núcleos GPU y el Neural Engine de los chips Apple Silicon (M1/M2/M3/M4) que están presentes en el hardware de referencia (MacBook Air).

### El problema con Docker en Mac

Docker en macOS corre dentro de una VM Linux (usando el framework de virtualización de Apple). **Metal** (API GPU de Apple), **MPS** (backend Metal de PyTorch) y el **Neural Engine** son APIs exclusivas de macOS y no están accesibles desde la VM Linux. En consecuencia, cualquier solución basada en Docker — ya sea Ollama, `transformers`, o `llama-cpp-python` — corre en modo CPU únicamente, independientemente del hardware subyacente.

### Opciones que sí funcionan (fuera del scope de este proyecto)

| Enfoque | Aceleración | Requisito |
|---|---|---|
| **Ollama nativo en el host** + app en Docker apunta a `host.docker.internal:11434` | ✅ Metal auto-detectado | `ollama serve` corriendo en el host Mac |
| **MLX** (`mlx-lm`, modelos `-mlx-bf16`) | ✅ GPU + memoria unificada | Ejecución nativa en macOS, sin Docker |
| **PyTorch MPS** (`torch.device("mps")`) | ✅ Núcleos GPU | Ejecución nativa en macOS, sin Docker |

La opción más simple para un usuario que quiera mayor velocidad sería correr Ollama nativamente y cambiar una variable de entorno: `OLLAMA_BASE_URL=http://host.docker.internal:11434`. Esto daría una mejora de ~3–5× en latencia en chips M-series sin cambiar ninguna línea del código de la aplicación.

### Por qué no se implementó

El requisito del proyecto es que **todo corra dentro de Docker** con un único `docker compose up --build`. Una arquitectura que requiere pasos manuales fuera de Docker (instalar Ollama nativo, iniciar `ollama serve`) viola ese requisito de portabilidad. Se documenta como opción de optimización para usuarios avanzados, no como configuración por defecto.

> **Nota sobre MLX:** Ollama provee variantes MLX de algunos modelos (e.g., `gemma4:e2b-mlx-bf16`). Sin embargo, estas variantes también requieren ejecución nativa en macOS y no funcionan dentro de un contenedor Linux.

---

## 13. Reproducibilidad

Para reproducir este benchmark en cualquier entorno con Ollama corriendo:

```bash
# Instalar dependencias
pip3 install requests

# Ejecutar benchmark completo
python3 eval/benchmark.py

# Ejecutar un modelo específico
python3 eval/benchmark.py qwen2.5:1.5b

# Ver resultados
cat eval/results.json
```

Los resultados se guardan automáticamente en `eval/results.json`.

---

*Documento generado como parte del proceso de selección de modelo e investigación de frameworks para el trabajo práctico de Nivii — Mayo 2026.*
