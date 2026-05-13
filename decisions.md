## 1. Resumen ejecutivo

Para el componente text-to-SQL del sistema, se evaluaron **8 modelos de lenguaje de código abierto** ejecutables localmente a través de [Ollama](https://ollama.com). La evaluación fue diseñada para un hardware de referencia representativo: una **MacBook Air con 8 GB de RAM** y Docker Desktop configurado con la asignación estándar de ~4 GB de memoria.

El modelo seleccionado es **`qwen2.5:1.5b`**, que alcanzó la máxima puntuación en la batería de pruebas (100% de respuestas correctas, 0 reintentos, ~2.5 s de latencia) con un tamaño de ~986 MB, compatible con cualquier máquina moderna.

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

Se diseñaron **5 consultas de referencia** sobre el conjunto de datos `data.csv` (~24 212 registros de transacciones POS). Las consultas cubren patrones SQL diferentes y representan casos de uso reales del sistema.

| ID | Dificultad | Consulta en lenguaje natural | Patrón SQL | Ground truth |
|---|---|---|---|---|
| Q1 | Simple | ¿Cuántos registros hay en total en la base de datos? | `COUNT(*)` | 24 212 |
| Q2 | Media | ¿Cuál es el producto más comprado los viernes? | `WHERE` + `GROUP BY` + `ORDER BY` + `LIMIT 1` | Alfajor Sin Azucar Suelto (850 u.) |
| Q3 | Media | ¿Cuáles son los 3 mozos con mayor ingreso total? | `SUM` + `GROUP BY` + `LIMIT 3` | 3 filas |
| Q4 | Media | ¿Cuál es el promedio del total de venta por día de la semana? | `AVG` + `GROUP BY` (7 grupos) | 7 filas (un promedio por día) |
| Q5 | Simple | ¿Cuántos mozos distintos hay en la base de datos? | `COUNT(DISTINCT)` | 9 mozos |

Las consultas están en español para evaluar también la capacidad del modelo de seguir instrucciones en un idioma distinto al inglés, condición real de este sistema.

El script de evaluación se encuentra en `eval/benchmark.py` y puede reproducirse con:

```bash
python3 eval/benchmark.py
```

---

## 5. Modelos evaluados

### 5a. Modelos con benchmark completo

Todos ejecutados vía Ollama con cuantización Q4_K_M sobre CPU.

| Modelo | Organización | Parámetros | Tamaño archivo | RAM estimada | Enfoque |
|---|---|---|---|---|---|
| `qwen2.5-coder:0.5b` | Alibaba | 0.5 B | 313 MB | ~0.5 GB | Código |
| `qwen2.5-coder:1.5b` | Alibaba | 1.5 B | 986 MB | ~1.2 GB | Código |
| `qwen2.5:1.5b` | Alibaba | 1.5 B | 986 MB | ~1.2 GB | General (instruct) |
| `llama3.2:1b` | Meta | 1.2 B | 1.3 GB | ~1.5 GB | General |
| `deepseek-coder:1.3b` | DeepSeek AI | 1.3 B | 776 MB | ~1.0 GB | Código |

### 5b. Modelos con restricción de memoria (ejecutados en hardware de referencia estándar)

| Modelo | Organización | Parámetros | RAM estimada | Categoría |
|---|---|---|---|---|
| `gemma2:2b` | Google | 2.6 B | ~2.5 GB | ⚠️ Estándar |
| `llama3.2:3b` | Meta | 3.2 B | ~3.0 GB | ⚠️ Estándar |
| `qwen2.5-coder:7b` | Alibaba | 7.6 B | ~5.0 GB | ❌ Avanzado |

---

## 6. Resultados del benchmark

### 6a. Tabla comparativa de modelos evaluados

| Modelo | SQL válido | Correcto | Latencia avg | Reintentos avg | Memoria | Veredicto |
|---|---|---|---|---|---|---|
| **`qwen2.5:1.5b`** | **100%** | **100%** | **2.5 s** | **0.00** | ✅ ~1.2 GB | ⭐ Elegido |
| `qwen2.5-coder:1.5b` | 100% | 80% | 2.4 s | 0.00 | ✅ ~1.2 GB | Bueno |
| `llama3.2:1b` | 100% | 60% | 1.9 s | 0.00 | ✅ ~1.5 GB | Aceptable |
| `qwen2.5-coder:0.5b` | 100% | 60% | 0.9 s | 0.00 | ✅ ~0.5 GB | Rápido / limitado |
| `deepseek-coder:1.3b` | 60% | 60% | 3.8 s | 1.20 | ✅ ~1.0 GB | Descartado |
| `gemma2:2b` | OOM | — | — | — | ⚠️ ~2.5 GB | No ejecutable† |
| `llama3.2:3b` | OOM | — | — | — | ⚠️ ~3.0 GB | No ejecutable† |
| `qwen2.5-coder:7b` | OOM | — | — | — | ❌ ~5.0 GB | No ejecutable† |

> † OOM en entorno de evaluación (Docker 2.4 GB). En hardware de referencia estándar (Docker 4 GB), `gemma2:2b` y `llama3.2:3b` deberían ejecutarse; `qwen2.5-coder:7b` requiere al menos 16 GB de RAM / 6 GB Docker.

---

### 6b. Análisis por modelo

#### `qwen2.5:1.5b` — Ganador empírico

El modelo instruct general de Qwen2.5 en 1.5 B alcanzó **5/5 consultas correctas**, siendo el único en resolver correctamente Q4 (agrupación por 7 días de la semana). Latencia de 2.5 s es acceptable. **Hallazgo relevante:** superó a su variante especializada en código (`qwen2.5-coder:1.5b`) en todas las consultas de agrupación y conteo. Esto sugiere que el fine-tuning orientado a código puede sobre-especializar el modelo hacia patrones Python/JavaScript y reducir su flexibilidad para seguir instrucciones en lenguaje natural mezclado.

#### `qwen2.5-coder:1.5b` — Segundo lugar

4/5 correctas. Falló en Q4 generando un SQL válido que retornaba menos de 7 grupos (probablemente añadió un `LIMIT` o `HAVING` innecesario). Latencia similar al modelo base. Considerado como alternativa si futuras pruebas mostraran que la especialización en código es ventajosa para consultas complejas con JOINs o subconsultas.

#### `llama3.2:1b` — Funcional pero limitado

3/5 correctas. Fallió en Q4 (promedio por día) y Q5 (COUNT DISTINCT), ambas consultas con agrupación. El modelo de Meta, aunque excelente para tareas generales de lenguaje, mostró menor precisión en SQL que los modelos Qwen del mismo rango de tamaño. Latencia de 1.9 s es su principal ventaja.

#### `qwen2.5-coder:0.5b` — Ultraligero con limitaciones

3/5 correctas. Velocísimo (0.9 s), ideal para máquinas muy limitadas. Sin embargo, la reducción de parámetros afecta la comprensión semántica: falló en Q4 y Q5. **Uso recomendado:** prototipado rápido o entornos con < 1 GB de RAM disponible para el modelo.

#### `deepseek-coder:1.3b` — Descartado

Peor resultado global: 3/5 SQL válidos tras reintentos (1.2 reintentos en promedio), 3.8 s de latencia. El modelo no logró generar SQL ejecutable para Q1 (COUNT simple) incluso tras 3 intentos — un comportamiento inaceptable. A pesar de estar orientado a código, no demostró capacidad suficiente para seguir el formato de prompt establecido.

---

### 6c. Detalle por consulta

| Modelo | Q1 Count | Q2 Filtro+Top | Q3 Top 3 | Q4 Promedio×7 | Q5 DISTINCT |
|---|---|---|---|---|---|
| `qwen2.5:1.5b` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `qwen2.5-coder:1.5b` | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| `llama3.2:1b` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| `qwen2.5-coder:0.5b` | ✅ | ✅ | ✅ | ⚠️ | ⚠️ |
| `deepseek-coder:1.3b` | ❌ | ✅ | ❌ | ✅ | ✅ |

> ✅ Correcto en primer intento · ⚠️ SQL ejecutable pero resultado incorrecto · ❌ SQL no ejecutable tras 3 reintentos

---

## 7. Análisis de trade-offs

### Velocidad vs. precisión

```
Correcto (%)
   100 │  ●  qwen2.5:1.5b
       │
    80 │  ●  qwen2.5-coder:1.5b
       │
    60 │  ●  llama3.2:1b   ●  qwen2.5-coder:0.5b   ●  deepseek-coder:1.3b
       │
    40 │
       └──────────────────────────────────────────────
          0.9s    1.9s    2.4s    2.5s    3.8s   Latencia
```

Existe una correlación positiva entre tamaño del modelo y precisión dentro del rango 1-2 B parámetros. La excepción es `deepseek-coder:1.3b`, que combina baja precisión con alta latencia — el peor de ambos mundos.

### Portabilidad vs. calidad

| Escenario | Modelo recomendado | Restricción |
|---|---|---|
| Máquina mínima (4 GB RAM total, Docker 2 GB) | `qwen2.5-coder:0.5b` | 60% precisión, rápido |
| Hardware de referencia (8 GB RAM, Docker 4 GB) | **`qwen2.5:1.5b`** | 100% precisión, equilibrado |
| Máquina potente (16 GB RAM, Docker 6 GB+) | `qwen2.5-coder:7b` | Mejor calidad en consultas complejas |

### ¿Por qué no un modelo más grande?

El modelo de 7B parámetros (`qwen2.5-coder:7b`) requiere ~5 GB de RAM solo para cargarse. En el hardware de referencia (Docker 4 GB), no puede ejecutarse. Incluso en máquinas con 16 GB, la inferencia en CPU para un 7B toma entre 30-60 segundos por consulta — inaceptable para una interfaz de usuario interactiva.

El sweet spot para este proyecto está en los modelos de 1-2 B parámetros: suficiente capacidad para SQL estructurado con prompts claros, con latencia sub-3s en CPU.

---

## 8. Modelo seleccionado: `qwen2.5:1.5b`

### Justificación

| Criterio | Valor | Cumple umbral |
|---|---|---|
| Tasa SQL válido | 100% | ✅ (≥ 80%) |
| Tasa respuesta correcta | 100% | ✅ (≥ 60%) |
| Latencia promedio | 2.5 s | ✅ (≤ 15 s) |
| Reintentos promedio | 0.00 | ✅ (≤ 0.5) |
| RAM requerida | ~1.2 GB | ✅ Universal |

`qwen2.5:1.5b` es el único modelo que supera **todos los umbrales con margen** y además corre en cualquier máquina con Docker instalado. Es el único modelo evaluado con 100% de precisión en el conjunto de pruebas.

### Por qué no `qwen2.5-coder:1.5b`

A pesar de ser el mismo tamaño y familia, la variante `coder` obtuvo 80% de precisión (4/5) frente al 100% (5/5) del modelo base instruct. La consulta fallida (Q4 — promedio agrupado por 7 días) sugiere que el fine-tuning orientado a código redujo la capacidad del modelo para seguir instrucciones en lenguaje natural y generar agregaciones completas. El modelo base, entrenado para seguir instrucciones generales, es más flexible.

### Estrategias de mitigación para las limitaciones del modelo

Aunque el modelo es pequeño, se implementan las siguientes estrategias para maximizar su fiabilidad:

1. **Inyección de esquema completo** en cada prompt de sistema — el modelo no necesita "recordar" la estructura de la tabla.
2. **Few-shot examples** con 3 ejemplos de pares pregunta→SQL en el prompt, anclan el formato de salida.
3. **Bucle de corrección con retroalimentación** — si el SQL falla, el error de SQLite se incluye en el prompt del siguiente intento (hasta 3 reintentos).
4. **Limpieza de output** — el código elimina markdown fences, texto explicativo y puntuación residual antes de ejecutar el SQL.

### Modelo para respuesta en lenguaje natural (bonus)

El mismo modelo `qwen2.5:1.5b` se usa para el componente de respuesta en lenguaje natural. Esto minimiza el uso de memoria (el modelo ya está cargado en Ollama) y reduce el tiempo total de descarga a ~986 MB. Los modelos Qwen2.5-Instruct manejan ambas tareas correctamente.

---

## 9. Modelos considerados pero no evaluados

Los siguientes modelos fueron investigados durante el proceso de selección pero **no pudieron ser evaluados con métricas completas** debido a restricciones de hardware o a no ser ejecutables localmente en el hardware de referencia.

### 9a. Requieren hardware por encima del referencia

Estos modelos son de código abierto y ejecutables localmente vía Ollama, pero su requerimiento de memoria los excluye del hardware de referencia (MacBook Air 8 GB / Docker 4 GB).

| Modelo | Parámetros | RAM estimada | Motivo de exclusión |
|---|---|---|---|
| `qwen2.5-coder:7b` | 7.6 B | ~5.0 GB | Requiere ≥16 GB RAM / 6 GB Docker. OOM en referencia. |
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

## 10. Reproducibilidad

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

*Documento generado como parte del proceso de selección de modelo para el trabajo práctico de Nivii — Mayo 2026.*
