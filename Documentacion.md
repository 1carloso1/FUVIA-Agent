# Documentación Técnica — Pipeline RAG
## Sistema de Soporte a Decisiones para Dosificación de Concreto (FUVIA)

---

## 0. Pipeline de Construcción del RAG

El proceso de construcción del sistema RAG siguió un pipeline estructurado de 10 pasos, diseñado para garantizar la calidad del texto extraído antes de la indexación. El pipeline distingue entre una fase de preparación manual (pasos 1–5) y una fase automatizada por scripts (pasos 6–10).

```
┌─────────────────────────────────────────────────────────────────┐
│                     FASE 1 — PREPARACIÓN                        │
│                        (manual)                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Auditar el PDF original                                     │
│     └─ Identificar estructura, número de columnas y tablas      │
│                                                                 │
│  2. Eliminar contenido fuera del scope                          │
│     └─ Portadas, índices, referencias bibliográficas,           │
│        capítulos no relevantes para el agente                   │
│                                                                 │
│  3. Identificar páginas problemáticas                           │
│     └─ Tablas en formato landscape, texto como imagen,          │
│        páginas con OCR fallido                                  │
│                                                                 │
│  4. Aplicar OCRmyPDF                                            │
│     └─ ocrmypdf --force-ocr --language eng                      │
│              --rotate-pages --deskew                            │
│                                                                 │
│  5. Verificar calidad del OCR                                   │
│     └─ Confirmar legibilidad del texto extraído,                │
│        documentar páginas no recuperables                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   FASE 2 — AUTOMATIZACIÓN                       │
│                       (scripts)                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  6. python preprocess_master.py                                 │
│     └─ Detecta layout por página (doble columna / CODE|COMM)   │
│        Reconstruye orden de lectura correcto                    │
│        Detecta y enriquece tablas con [TABLE_CONTEXT]           │
│        Output: data_clean/<documento>/page_XXX.txt              │
│                                                                 │
│  7. python audit_tables.py                                      │
│     └─ Genera índice de tablas por documento                   │
│        Clasifica títulos reales vs. genéricos                   │
│        Output: audit_report/audit_index.txt                     │
│                                                                 │
│  8. Revisión del índice de auditoría                            │
│     └─ Verificar que tablas críticas fueron detectadas          │
│        Documentar limitaciones de extracción                    │
│        Ajustar umbrales si es necesario                         │
│                                                                 │
│  9. python ingest.py                                            │
│     └─ Vectoriza cada página con BAAI/bge-small-en-v1.5        │
│        Indexa en ChromaDB con metadata de página                │
│        Control de duplicados por source_id                      │
│                                                                 │
│  10. python query.py                                            │
│      └─ Valida el pipeline con consultas de prueba             │
│         Verifica citación correcta de fuentes                   │
│         Confirma soporte multilingüe (ES/EN)                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

> **Nota metodológica:** Los pasos 1–5 se ejecutaron una sola vez por documento. Los pasos 6–10 son reproducibles y pueden re-ejecutarse ante cambios en el stack normativo o ajustes en los parámetros de preprocesamiento.

---

## 1. Stack Normativo Indexado

El sistema RAG fue construido sobre los siguientes documentos normativos. Todos los PDFs fueron preprocesados mediante OCRmyPDF con los flags `--force-ocr --language eng --rotate-pages --deskew` para asegurar extracción de texto consistente previo a la indexación.

| Documento | Versión | Contenido | Capítulos indexados |
|---|---|---|---|
| ACI 211.1 | -22 | Dosificación de concreto convencional (NC) | 1–9 |
| ACI 211.4R | -08 | Dosificación de concreto de alta resistencia (HPC) | 1–8 |
| ACI 318-19 | -19 | Requisitos estructurales y de durabilidad | 2, 9, 10, 18, 19, 26 |
| ASTM C150 | /C150M-22 | Especificaciones de cemento Portland | Completo |
| ASTM C33 | /C33M-13 | Especificaciones de agregados | Completo |
| ASTM C494 | /C494M-19 | Especificaciones de aditivos químicos | Completo |

**Total de páginas indexadas:** ~310 páginas de contenido técnico normativo.

---

## 2. Estrategia de Preprocesamiento

### 2.1 Problema identificado

Todos los documentos del stack utilizan un layout de doble columna. La extracción directa con PyMuPDF mezclaba ambas columnas en el mismo chunk, generando texto incoherente que el modelo de embeddings no podía vectorizar correctamente.

El ACI 318-19 presenta adicionalmente un layout **CODE | COMMENTARY**, donde la columna izquierda contiene el texto prescriptivo de la norma y la columna derecha contiene la explicación editorial. Ambas columnas aportan valor semántico al sistema de recuperación.

### 2.2 Solución implementada

Se desarrolló `preprocess_master.py`, un script de preprocesamiento que:

- **Detecta automáticamente** el layout de cada página por contenido, sin configuración manual por documento
- Reconstruye el **orden de lectura correcto** (columna izquierda completa → columna derecha) para documentos de texto continuo
- Aplica **etiquetado semántico** `[CODE]` y `[COMMENTARY]` para el ACI 318-19, preservando ambas columnas sin mezcla
- Genera **un archivo `.txt` por página** en una carpeta por documento, produciendo unidades semánticas naturales para el chunking del RAG
- Incluye **metadata de página** en cada archivo (documento, número de página, layout detectado) para permitir citación exacta en los reportes del agente

### 2.3 Detección y enriquecimiento de tablas

Las tablas de los documentos ACI/ASTM no contienen bordes detectables por PyMuPDF (`find_tables()` retorna 0 resultados), ya que están construidas con texto posicionado manualmente en el PDF. Se implementó una estrategia heurística basada en patrones de contenido:

- Se definió un vocabulario de **50+ patrones técnicos** cubriendo propiedades de concreto, cemento, agregados y aditivos
- Un bloque de texto se clasifica como tabla cuando contiene **5 o más patrones** del vocabulario
- Se implementó un algoritmo de **lookback de 5 bloques** para recuperar el título real de la tabla desde el bloque precedente
- Cada tabla detectada recibe una etiqueta `[TABLE_CONTEXT]` con descripción semántica generada automáticamente, que es el texto que el modelo de embeddings vectoriza para permitir recuperación por contenido

---

## 3. Arquitectura del Sistema RAG

### 3.1 Componentes

| Componente | Tecnología | Justificación |
|---|---|---|
| Modelo de embeddings | `BAAI/bge-small-en-v1.5` | Optimizado para inglés técnico; documentos ACI/ASTM en inglés |
| Base de datos vectorial | ChromaDB (persistente) | Almacenamiento local sin costo; adecuado para escala de prototipo |
| Framework RAG | LlamaIndex | Superior manejo de documentos técnicos con tablas y referencias cruzadas |
| LLM de generación | Claude Sonnet (Anthropic API) | Alta precisión en instrucciones estructuradas y generación de reportes técnicos |
| Retriever | Híbrido BM25 + semántico | BM25 recupera cláusulas por número exacto; semántico recupera por concepto |

### 3.2 Pipeline de consulta

```
Pregunta del usuario (español o inglés)
        ↓
Detección de idioma (LLM)
        ↓
Traducción al inglés si es necesario — preservando términos técnicos
        ↓
Retrieval híbrido: BM25 (top-2) + semántico (top-3)
        ↓
Deduplicación por node_id
        ↓
Síntesis con prompt normativo especializado
        ↓
Respuesta en el idioma original del usuario con citación de fuentes
```

### 3.3 Soporte multilingüe

El sistema acepta consultas en español e inglés. Dado que los documentos normativos están en inglés y el modelo de embeddings está optimizado para ese idioma, se implementó una estrategia de **query translation**: la pregunta del usuario se traduce al inglés antes del retrieval para maximizar la precisión semántica, pero el LLM genera la respuesta en el idioma original de la consulta. Los términos técnicos (f'c, w/cm, MPa) se preservan sin traducción en ambas direcciones.

---

## 4. Auditoría de Calidad del Preprocesamiento

Se desarrolló `audit_tables.py`, un script de auditoría que analiza los archivos preprocesados y genera un índice de todas las tablas detectadas por documento, clasificando cada una según la calidad del título extraído.

### 4.1 Resultados de la auditoría

| Documento | Tablas detectadas | Título real | Título genérico | Calidad |
|---|---|---|---|---|
| ACI 211.1-22 | 41 | 18 | 23 | 44% |
| ACI 211.4R-08 | 35 | 10 | 25 | 29% |
| ACI 318-19 | 23 | 9 | 14 | 39% |
| ASTM C150-22 | 4 | 1 | 3 | 25% |
| ASTM C33-13 | 8 | 3 | 5 | 38% |
| ASTM C494-19 | 10 | 3 | 7 | 30% |
| **TOTAL** | **121** | **44** | **77** | **36%** |

### 4.2 Interpretación

La precisión del 36% en títulos reales refleja las limitaciones del OCR en los PDFs fuente — los encabezados de tabla frecuentemente contienen caracteres corrompidos que el algoritmo de lookback no puede identificar. Sin embargo, **el título no es el vector que utiliza el retriever**: el sistema recupera tablas por el `[TABLE_CONTEXT]`, que en el 100% de los casos contiene descripción semántica correcta del contenido de la tabla.

La validación funcional del sistema confirma este comportamiento: ante la consulta *"¿Cuál es la relación w/cm máxima para clase de exposición F2?"*, el retriever recuperó correctamente la `Tabla 19.3.2.1 del ACI 318-19` con el valor `w/cm = 0.45`, f'c mínimo de 4,500 psi, y la referencia al contenido de aire según la Tabla 19.3.3.1.

---

## 5. Limitaciones Conocidas

### 5.1 Tabla 3 del ASTM C33/C33M-13

La Tabla 3 (*Grading Requirements for specific coarse aggregate sizes*) no fue recuperable debido a falla del OCR en las páginas en formato landscape del PDF fuente. Esta tabla no es crítica para el caso de uso principal del sistema, que se enfoca en la dosificación estándar cubierta por las Tablas 1 y 2 del mismo documento.

### 5.2 Precisión de títulos de tabla

Como se describe en la sección 4.2, el 64% de las tablas detectadas tienen título genérico (`Normative table`) debido a limitaciones del OCR en los PDFs fuente. Esto no afecta la recuperación semántica pero sí la legibilidad de las fuentes citadas en los reportes del agente.

### 5.3 Inconsistencia de métricas de retrieval

El retriever híbrido BM25 + semántico produce scores en métricas distintas (distancia coseno para el retriever semántico, sin score para BM25). Esto genera inconsistencia en los scores mostrados al usuario, donde algunos chunks presentan valores en rango 0–1 y otros valores superiores a 1. Esta limitación es de presentación y no afecta la calidad del retrieval.

### 5.4 Cobertura del ACI 318-19

Se indexaron únicamente los capítulos relevantes para el scope del sistema (2, 9, 10, 18, 19 y 26 de los 27 capítulos totales). Consultas sobre temas fuera de este scope — diseño de cimentaciones, muros, diafragmas, estructuras prefabricadas — no serán respondidas por el sistema, el cual notificará al usuario qué cláusula adicional sería necesaria.

---

## 6. Validación Funcional

### 6.1 Caso de prueba ejecutado

| Campo | Valor |
|---|---|
| Consulta | *"¿Cuál es la relación w/cm máxima para clase de exposición F2?"* |
| Idioma de entrada | Español |
| Query de retrieval | *"What is the maximum w/cm ratio for exposure class F2?"* |
| Chunks recuperados | 5 (3 semánticos + 2 BM25) |
| Fuente principal recuperada | ACI 318-19, Tabla 19.3.2.1 |

### 6.2 Respuesta generada

El sistema produjo una respuesta normativamente correcta que incluye:

- Valor de w/cm máximo (0.45) con referencia explícita a tabla y norma
- f'c mínimo requerido (4,500 psi)
- Requisito de contenido de aire referenciando Tabla 19.3.3.1
- Nota al pie sobre inaplicabilidad al concreto ligero
- Respuesta generada en español, idioma original de la consulta

Este resultado valida que el pipeline completo — preprocesamiento, indexación, retrieval híbrido y generación — funciona correctamente para el caso de uso central del sistema.

---

*Documentación generada durante el desarrollo del sistema FUVIA — Fase 1: RAG Foundation.*
*Fecha de validación: Mayo 2026.*
