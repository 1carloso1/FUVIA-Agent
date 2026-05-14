# Stack Normativo — FUVIA 
# Justificación de Selección de Capítulos

---

## CRITERIO GENERAL DE FILTRADO

Todo documento del stack sigue la misma regla base:

**Se omite siempre:** portada, página de créditos, tabla de contenidos, índice alfabético,
listas de referencias bibliográficas y apéndices fuera del scope del agente.

**Justificación:** El sistema RAG convierte texto en vectores semánticos para búsqueda
por similitud. El contenido no técnico (portadas, créditos, índices, bibliografías) genera
vectores que contaminan el espacio de búsqueda y reducen la precisión del retrieval.
Indexar solo contenido técnico consultable maximiza la calidad de las respuestas del agente.

---

## ACI 211.1-22
**Propósito en el sistema:** Dosificación de concreto convencional (NC).
Proceso completo de selección de proporciones de mezcla.

| Capítulo | Título | Decisión |
|---|---|---|
| Chapter 1 | Introduction and Scope | ✅ Mantener |
| Chapter 2 | Notation and Definitions | ✅ Mantener |
| Chapter 3 | Concrete Properties | ✅ Mantener |
| Chapter 4 | Background Information | ✅ Mantener |
| Chapter 5 | Proportion Selection Procedure | ✅ Mantener |
| Chapter 6 | Effects of Chemical Admixtures | ✅ Mantener |
| Chapter 7 | Effects of Supplementary Cementitious Materials | ✅ Mantener |
| Chapter 8 | Trial Batching | ✅ Mantener |
| Chapter 9 | Sample Computations | ✅ Mantener |
| Chapter 10 | References | ❌ Omitir |
| Appendix A | Laboratory Tests | ❌ Omitir |
| Appendix B | High-Density Concrete | ❌ Omitir |

**Justificación de omisiones:**
- **Chapter 10:** Lista de referencias bibliográficas. No contiene contenido normativo
  consultable — solo citas a otros documentos. Ruido puro para el RAG.
- **Appendix A:** Procedimientos de ensayo de laboratorio. El agente no ejecuta ni
  valida ensayos físicos — ese scope pertenece a EMOCVision, no a este sistema.
- **Appendix B:** Dosificación de concreto de alta densidad (blindaje, contención
  nuclear). Fuera del scope del agente que cubre NC, HPC y RAC estructural.

---

## ACI 211.4R-08
**Propósito en el sistema:** Dosificación de concreto de alta resistencia (HPC).
Proporciones con fly ash, silica fume y slag cement.

| Capítulo | Título | Decisión |
|---|---|---|
| Chapter 1 | Introduction and Scope | ✅ Mantener |
| Chapter 2 | Notation and Definitions | ✅ Mantener |
| Chapter 3 | Performance Requirements | ✅ Mantener |
| Chapter 4 | Concrete Materials | ✅ Mantener |
| Chapter 5 | High-Strength Concrete Mixture Properties | ✅ Mantener |
| Chapter 6 | Mixture Proportioning using Fly Ash | ✅ Mantener |
| Chapter 7 | Mixture Proportioning using Silica Fume | ✅ Mantener |
| Chapter 8 | Mixture Proportioning using Slag Cement | ✅ Mantener |
| Chapter 9 | References | ❌ Omitir |

**Justificación de omisiones:**
- **Chapter 9:** Lista de referencias bibliográficas y estándares citados.
  No contiene contenido normativo propio — mismo criterio que Chapter 10 del ACI 211.1.

---

## ACI 318-19
**Propósito en el sistema:** Requisitos estructurales y de durabilidad del concreto.
Resistencia mínima por elemento, exposición ambiental y zona sísmica.

| Capítulo | Título | Decisión |
|---|---|---|
| Chapter 2 | Notation and Terminology | ✅ Mantener — prioridad baja |
| Chapter 9 | Beams | ✅ Mantener — §9.2 y §9.3 |
| Chapter 10 | Columns | ✅ Mantener — §10.2 y §10.3 |
| Chapter 18 | Earthquake-Resistant Structures | ✅ Mantener — §18.2, §18.6, §18.7 |
| Chapter 19 | Concrete: Design and Durability Requirements | ✅ Mantener completo |
| Chapter 26 | Construction Documents and Inspection | ✅ Mantener — §26.4 principalmente |
| Chapters 1, 3-8, 11-17, 20-27 | Resto del documento | ❌ Omitir |

**Justificación de omisiones:**
- **Chapters omitidos:** ACI 318-19 tiene 27 capítulos y ~600 páginas. El agente cubre
  exclusivamente dosificación y propiedades del concreto para elementos estructurales
  comunes (columnas, vigas). Capítulos sobre cimentaciones, muros, diafragmas, anclajes,
  prefabricado, postensado y evaluación de estructuras existentes están fuera del scope
  definido y generarían retrieval contaminado con contenido irrelevante.
- **Chapter 2 — prioridad baja:** Se indexa como referencia de terminología y notación.
  El agente lo consulta solo para definir símbolos o términos encontrados en otros
  capítulos, no como fuente primaria de respuestas.

---

## ASTM C150/C150M-22
**Propósito en el sistema:** Especificaciones de cemento Portland.
Clasificación por tipo y criterios de selección según condición de exposición.

**Decisión:** ✅ Indexar completo (omitir portada, créditos y tabla de contenidos)

**Justificación:** Documento de ~10 páginas de contenido técnico puro.
No contiene secciones fuera del scope — todo el cuerpo es consultable directamente.

---

## ASTM C33/C33M-13
**Propósito en el sistema:** Especificaciones de agregados finos y gruesos.
Requisitos de granulometría, limpieza y clasificación — inputs directos de FUVIA.

**Decisión:** ✅ Indexar completo (omitir portada, créditos y tabla de contenidos)

**Justificación:** Documento de ~15 páginas. Versión 2013 — las especificaciones de
agregados son de las más estables en normativa ASTM; las diferencias entre la edición
-13 y la más reciente (-18) no afectan el scope del sistema. Completamente defendible
en contexto académico documentando la versión utilizada.

---

## ASTM C494/C494M-19
**Propósito en el sistema:** Especificaciones de aditivos químicos.
Clasificación por tipo y criterios de uso en HPC con baja relación agua/cemento.

**Decisión:** ✅ Indexar completo (omitir portada, créditos y tabla de contenidos)

**Justificación:** Documento de ~12 páginas de contenido técnico puro.
No contiene secciones fuera del scope del agente.

---

## RESUMEN EJECUTIVO

| Documento | Versión | Contenido | Capítulos indexados |
|---|---|---|---|
| ACI 211.1 | -22 | Dosificación de concreto convencional (NC) | 1–9 |
| ACI 211.4R | -08 | Dosificación de concreto de alta resistencia (HPC) | 1–8 |
| ACI 318-19 | -19 | Requisitos estructurales y de durabilidad | 2, 9, 10, 18, 19, 26 |
| ASTM C150 | /C150M-22 | Especificaciones de cemento Portland | Completo |
| ASTM C33 | /C33M-13 | Especificaciones de agregados | Completo |
| ASTM C494 | /C494M-19 | Especificaciones de aditivos químicos | Completo |

**Total de páginas indexadas:** ~310 páginas de contenido técnico normativo.
