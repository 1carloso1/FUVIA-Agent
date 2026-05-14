"""
preprocess_master.py
====================
Script maestro de preprocesamiento para el stack normativo FUVIA.
Reemplaza completamente preprocess_pdfs.py.

ESTRATEGIA:
  1. Detección automática de layout por página:
     - Detecta CODE/COMMENTARY por presencia de encabezados
     - No requiere configuración por documento
  
  2. Detección universal de tablas:
     - Funciona en cualquier columna (izquierda, derecha, full-width)
     - Lookback de 5 bloques para título real
     - Patrones ampliados para ACI y ASTM
  
  3. Output por página:
     - Una carpeta por documento
     - Un .txt por página
     - Metadata de página incluida para citación exacta

OUTPUT:
  data_clean/
  ├── ACI_211.1-22/
  │   ├── page_001.txt
  │   └── ...
  ├── ACI_318-19_selected/
  │   └── ...
  └── ...

USO:
    pip install pymupdf
    python preprocess_master.py

SIGUIENTES PASOS:
    1. Verifica los .txt generados
    2. Borra ./chroma_db
    3. Ejecuta ingest.py
"""

import re
import fitz
from pathlib import Path

INPUT_DIR  = "./data"
OUTPUT_DIR = "./data_clean"

# ----------------------------------------------------------------
# PATRONES DE DETECCIÓN DE TABLAS
# Ampliados para cubrir ACI (concreto) y ASTM (materiales)
# ----------------------------------------------------------------
TABLE_PATTERNS = [
    # Concreto y mezclas
    "w/cm", "w/c", "f'c", "f'c",
    "0.40", "0.45", "0.50", "0.55", "0.60",
    "2500", "3000", "3500", "4000", "4500", "5000",
    "Exposure class", "exposure class",
    # Resistencia y durabilidad
    "psi", "MPa", "ksi",
    "minimum", "maximum", "Minimum", "Maximum",
    "N/A", "percent", "Percent",
    # Cemento
    "Type I", "Type II", "Type III", "Type IV", "Type V",
    "ASTM C150", "ASTM C595", "ASTM C1157",
    "C3A", "C3S", "C2S", "C4AF",
    "Blaine", "fineness", "Fineness",
    "Loss on ignition", "loss on ignition",
    "Insoluble residue",
    # Agregados y granulometría
    "sieve", "Sieve", "passing", "Passing",
    "aggregate", "Aggregate",
    "3/8", "3/4", "1/2", "1-1/2",
    "No. 4", "No. 8", "No. 16", "No. 30", "No. 50", "No. 100", "No. 200",
    "mm (No.", "um (No.",
    "Nominal", "nominal",
    "Grading", "grading",
    "Fineness modulus", "fineness modulus",
    # Aditivos y químicos
    "admixture", "Admixture",
    "Type A", "Type B", "Type C", "Type D", "Type E", "Type F", "Type G",
    "water reduction", "Water reduction",
    "retarding", "Retarding", "accelerating", "Accelerating",
    "air-entraining", "Air-entraining",
    "chloride", "Chloride",
    "sulfate", "Sulfate",
    # Propiedades físicas
    "slump", "Slump",
    "air content", "Air content",
    "density", "Density",
    "absorption", "Absorption",
    "soundness", "Soundness",
    "strength", "Strength",
]

# Umbral mínimo de patrones para clasificar como tabla
TABLE_PATTERN_THRESHOLD = 5

# Umbrales de clasificación de columnas
COLUMN_SPLIT_RATIO     = 0.50
FULLWIDTH_LEFT_MARGIN  = 0.15
FULLWIDTH_RIGHT_MARGIN = 0.85
MERGE_GAP_THRESHOLD    = 14.0


# ----------------------------------------------------------------
# UTILIDADES COMPARTIDAS
# ----------------------------------------------------------------

def is_table_block(text: str) -> bool:
    """Detecta si un bloque es una tabla por patrones de contenido."""
    matches = sum(1 for p in TABLE_PATTERNS if p in text)
    return matches >= TABLE_PATTERN_THRESHOLD


def classify_block(block: tuple, page_width: float) -> str:
    """
    Clasifica un bloque según posición horizontal.
    Returns: 'fullwidth', 'left', o 'right'
    """
    x0, y0, x1, y1, *_ = block
    x0_norm = x0 / page_width
    x1_norm = x1 / page_width
    if x0_norm < FULLWIDTH_LEFT_MARGIN and x1_norm > FULLWIDTH_RIGHT_MARGIN:
        return "fullwidth"
    center = (x0_norm + x1_norm) / 2
    return "left" if center < COLUMN_SPLIT_RATIO else "right"


def merge_blocks(blocks: list, gap_threshold: float = MERGE_GAP_THRESHOLD) -> list:
    """
    Fusiona bloques contiguos de la misma columna en párrafos completos.
    Evita que cada línea se procese como bloque independiente.
    """
    blocks = [b for b in blocks if b[4] is not None and str(b[4]).strip()]
    if not blocks:
        return []

    merged  = []
    current = list(blocks[0])

    for block in blocks[1:]:
        if block[4] is None:
            continue
        gap         = block[1] - current[3]
        same_column = abs(block[0] - current[0]) < 30
        if gap < gap_threshold and same_column:
            current[3] = block[3]
            current[2] = max(current[2], block[2])
            current[4] = current[4].rstrip('\n') + ' ' + block[4].lstrip()
        else:
            merged.append(tuple(current))
            current = list(block)

    merged.append(tuple(current))
    return merged


def detect_code_commentary(page: fitz.Page) -> bool:
    """
    Detecta automáticamente si una página tiene layout CODE/COMMENTARY.
    Busca los encabezados 'CODE' y 'COMMENTARY' como bloques independientes
    en posiciones fijas — característica exclusiva del ACI 318-19.
    No requiere conocer el nombre del documento.
    """
    blocks = page.get_text("blocks")
    has_code        = False
    has_commentary  = False

    for block in blocks:
        text = block[4].strip() if block[4] else ""
        # Encabezados son bloques cortos con exactamente estas palabras
        if text in ("CODE", "Code"):
            has_code = True
        if text in ("COMMENTARY", "Commentary"):
            has_commentary = True
        if has_code and has_commentary:
            return True

    return False


def get_table_title(all_blocks: list, current_idx: int) -> str:
    """
    Busca hacia atrás hasta 5 bloques para encontrar el título real
    de una tabla. El título EMPIEZA con 'Table XX.XX' o 'TABLE'.
    """
    for j in range(current_idx - 1, max(current_idx - 6, -1), -1):
        text = all_blocks[j][2].strip() if len(all_blocks[j]) > 2 else ""
        if re.search(r"(Table|TABLE)\s+\d+[\.\d]*", text):
            match = re.search(r"(Table|TABLE)\s+\d+[\.\d]*[^\n]{0,50}", text)
            return match.group(0).strip()[:80]
    return None


def get_table_context(text: str) -> str:
    """
    Genera contexto semántico para una tabla basado en su contenido.
    Este texto es lo que el modelo de embeddings vectoriza para
    permitir retrieval correcto cuando se consulta por valores específicos.
    """
    parts = []

    # Concreto y mezclas
    if any(p in text for p in ["w/cm", "w/c"]):
        parts.append("maximum water-cementitious materials ratio w/cm limits")
    if any(p in text for p in ["f'c", "psi", "MPa"]):
        parts.append("compressive strength f'c requirements")
    if any(p in text for p in ["Exposure class", "exposure class"]):
        parts.append("exposure class requirements for concrete durability")
    if any(p in text for p in ["F0", "F1", "F2", "F3", "FO"]):
        parts.append("freezing and thawing exposure classes")
    if any(p in text for p in ["S0", "S1", "S2", "S3", "SO"]):
        parts.append("sulfate exposure classes")
    if any(p in text for p in ["W0", "W1", "W2", "WO"]):
        parts.append("water exposure classes")
    if any(p in text for p in ["C0", "C1", "C2", "CO"]):
        parts.append("chloride exposure classes and chloride ion content limits")
    if any(p in text for p in ["air content", "Air content", "Air Content"]):
        parts.append("air content requirements")

    # Cemento
    if any(p in text for p in ["Type I", "Type II", "Type III", "Type V", "ASTM C150"]):
        parts.append("portland cement type specifications and chemical requirements")
    if any(p in text for p in ["C3A", "C3S", "Blaine", "fineness", "Loss on ignition"]):
        parts.append("cement chemical and physical property limits")

    # Agregados
    if any(p in text for p in ["sieve", "Sieve", "passing", "Passing", "Grading", "grading"]):
        parts.append("aggregate grading and sieve analysis requirements")
    if any(p in text for p in ["No. 4", "No. 8", "No. 16", "3/8", "3/4", "mm (No."]):
        parts.append("particle size distribution limits by sieve size")
    if any(p in text for p in ["absorption", "Absorption", "soundness", "Soundness"]):
        parts.append("aggregate physical property limits")

    # Aditivos
    if any(p in text for p in ["admixture", "Admixture", "Type A", "Type B", "Type C"]):
        parts.append("chemical admixture type classification and performance requirements")
    if any(p in text for p in ["water reduction", "Water reduction", "retarding", "accelerating"]):
        parts.append("admixture water reduction and setting time effects")

    if not parts:
        parts.append("normative requirements for construction materials")

    return "This table specifies: " + "; ".join(parts) + "."


# ----------------------------------------------------------------
# EXTRACCIÓN DE PÁGINA
# ----------------------------------------------------------------

def extract_page(page: fitz.Page) -> str:
    """
    Extrae el contenido de una página con detección automática de layout.

    Flujo:
      1. Detectar si la página tiene layout CODE/COMMENTARY
      2. Separar bloques por columna
      3. Fusionar bloques fragmentados dentro de cada columna
      4. Detectar tablas en cualquier columna
      5. Reconstruir texto con etiquetas semánticas
    """
    page_width       = page.rect.width
    is_code_commentary = detect_code_commentary(page)

    blocks = sorted(page.get_text("blocks"), key=lambda b: b[1])

    # Separar por columna
    raw_fullwidth = []
    raw_left      = []
    raw_right     = []

    for block in blocks:
        text = block[4]
        if text is None or not str(text).strip():
            continue
        block_type = classify_block(block, page_width)
        if block_type == "fullwidth":
            raw_fullwidth.append(block)
        elif block_type == "left":
            raw_left.append(block)
        else:
            raw_right.append(block)

    # Fusionar bloques fragmentados dentro de cada columna
    fullwidth = merge_blocks(raw_fullwidth)
    left      = merge_blocks(raw_left)
    right     = merge_blocks(raw_right)

    # Construir lista unificada con tipo para procesamiento
    # Formato: (y0, block_type, text)
    all_blocks = []
    for b in fullwidth:
        all_blocks.append((b[1], "fullwidth", b[4].strip()))
    for b in left:
        all_blocks.append((b[1], "left", b[4].strip()))
    for b in right:
        all_blocks.append((b[1], "right", b[4].strip()))

    all_blocks.sort(key=lambda x: x[0])

    has_right_column   = len(right) > 0
    table_header_found = False
    lines              = []
    prev_type          = None

    for i, (_, block_type, text) in enumerate(all_blocks):
        if not text:
            continue
        if prev_type and prev_type != block_type:
            lines.append("")

        # Detectar tabla en cualquier columna — universal
        if is_table_block(text) and not table_header_found:
            title   = get_table_title(all_blocks, i) or "Normative table"
            context = get_table_context(text)
            lines.append(f"[TABLE: {title}]")
            lines.append(f"[TABLE_CONTEXT: {context}]")
            table_header_found = True
        elif not is_table_block(text):
            table_header_found = False

        # Renderizar según layout detectado
        if block_type == "fullwidth":
            lines.append(text)

        elif block_type == "left":
            if is_code_commentary and has_right_column:
                # Omitir encabezados CODE/COMMENTARY puros
                if text.strip() in ("CODE", "COMMENTARY", "Code", "Commentary"):
                    prev_type = block_type
                    continue
                lines.append(f"[CODE] {text}")
            else:
                lines.append(text)

        else:  # right
            if is_code_commentary and has_right_column:
                if text.strip() in ("CODE", "COMMENTARY", "Code", "Commentary"):
                    prev_type = block_type
                    continue
                lines.append(f"[COMMENTARY] {text}")
            else:
                lines.append(text)

        prev_type = block_type

    return "\n".join(lines)


# ----------------------------------------------------------------
# PROCESADOR PRINCIPAL
# ----------------------------------------------------------------

def process_pdf(pdf_path: Path, output_dir: Path):
    """
    Procesa un PDF completo y genera un .txt por página
    en una subcarpeta con el nombre del documento.
    """
    doc_name   = pdf_path.stem
    doc_dir    = output_dir / doc_name
    doc_dir.mkdir(exist_ok=True)

    doc         = fitz.open(str(pdf_path))
    total_pages = len(doc)

    pages_written = 0
    pages_empty   = 0
    tables_found  = 0
    cc_pages      = 0

    for page_num, page in enumerate(doc, start=1):
        content = extract_page(page)

        if not content.strip():
            pages_empty += 1
            continue

        # Estadísticas
        if "[TABLE:" in content:
            tables_found += content.count("[TABLE:")
        if "[CODE]" in content:
            cc_pages += 1

        # Metadata de página al inicio del archivo
        is_cc    = detect_code_commentary(page)
        layout   = "CODE/COMMENTARY" if is_cc else "continuous"
        header   = (
            f"[DOCUMENT: {doc_name}]\n"
            f"[PAGE: {page_num}/{total_pages}]\n"
            f"[LAYOUT: {layout}]\n"
            f"{'='*60}\n"
        )

        page_file = doc_dir / f"page_{page_num:03d}.txt"
        page_file.write_text(header + content, encoding="utf-8")
        pages_written += 1

    doc.close()

    print(f"  Páginas escritas    : {pages_written}/{total_pages}")
    print(f"  Páginas vacías      : {pages_empty}")
    print(f"  Páginas CODE/COMM   : {cc_pages}")
    print(f"  Tablas detectadas   : {tables_found}")
    print(f"  Output              : {doc_dir}/")

    return pages_written, tables_found


def main():
    input_path  = Path(INPUT_DIR)
    output_path = Path(OUTPUT_DIR)

    if not input_path.exists():
        print(f"ERROR: Directorio '{INPUT_DIR}' no encontrado.")
        return

    output_path.mkdir(exist_ok=True)

    pdf_files = sorted(input_path.glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: No se encontraron PDFs en '{INPUT_DIR}'.")
        return

    print(f"Documentos encontrados: {len(pdf_files)}")
    print(f"Output directory      : {OUTPUT_DIR}")
    print("=" * 60)

    total_pages  = 0
    total_tables = 0

    for pdf_file in pdf_files:
        print(f"\nProcesando: {pdf_file.name}")
        try:
            pages, tables = process_pdf(pdf_file, output_path)
            total_pages  += pages
            total_tables += tables
            print(f"  ✓ Completado")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    print("\n" + "=" * 60)
    print("Preprocesamiento completado.")
    print(f"  Total páginas procesadas : {total_pages}")
    print(f"  Total tablas detectadas  : {total_tables}")
    print(f"\nSIGUIENTES PASOS:")
    print(f"  1. Verifica las carpetas en ./{OUTPUT_DIR}/")
    print(f"     - Abre algunos page_XXX.txt y verifica coherencia")
    print(f"     - Busca [TABLE:] y [TABLE_CONTEXT:] en documentos clave")
    print(f"     - Verifica que ACI 318-19 tiene etiquetas [CODE]/[COMMENTARY]")
    print(f"     - Verifica que ASTM C33 tiene la tabla de granulometría")
    print(f"  2. Borra ./chroma_db")
    print(f"  3. Actualiza ingest.py para leer carpetas de .txt")
    print(f"  4. Ejecuta: python ingest.py")


if __name__ == "__main__":
    main()