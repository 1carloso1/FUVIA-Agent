"""
audit_tables.py
===============
Script de auditoría de tablas para el stack normativo FUVIA.

PROPÓSITO:
Antes de indexar, genera un reporte detallado de todas las tablas
detectadas en cada documento del stack. Permite verificar que las
tablas críticas están siendo capturadas correctamente y con el
contexto semántico adecuado.

ESTRATEGIA DE DETECCIÓN (en orden de prioridad):
  1. PyMuPDF find_tables() — detecta tablas con bordes reales
  2. Heurística por patrones — detecta tablas sin bordes (ACI 318-19)

OUTPUT:
  ./audit_report/audit_tables.txt — reporte completo
  ./audit_report/<documento>_tables.txt — tablas por documento

USO:
    pip install pymupdf pandas tabulate
    python audit_tables.py
"""

import fitz
import re
import os
from pathlib import Path

DATA_DIR   = "./data"
REPORT_DIR = "./audit_report"

# Mismos patrones que preprocess_pdfs.py
TABLE_PATTERNS = [
    "w/cm", "w/c", "psi", "MPa", "f'c",
    "0.40", "0.45", "0.50", "0.55",
    "2500", "3000", "3500", "4000", "4500", "5000",
    "Exposure class", "exposure class",
    "Table ", "Type I", "Type II", "Type V",
    "N/A", "ASTM C150", "ASTM C595",
    "aggregate", "Aggregate", "cement", "Cement",
    "admixture", "Admixture", "slump", "Slump",
    "sieve", "Sieve", "passing", "Passing",
    "minimum", "maximum", "Minimum", "Maximum",
]

COLUMN_SPLIT_RATIO     = 0.50
FULLWIDTH_LEFT_MARGIN  = 0.15
FULLWIDTH_RIGHT_MARGIN = 0.85


def is_table_block(text: str) -> bool:
    matches = sum(1 for p in TABLE_PATTERNS if p in text)
    return matches >= 3


def classify_block(block: tuple, page_width: float) -> str:
    x0, y0, x1, y1, text, *_ = block
    x0_norm = x0 / page_width
    x1_norm = x1 / page_width
    if x0_norm < FULLWIDTH_LEFT_MARGIN and x1_norm > FULLWIDTH_RIGHT_MARGIN:
        return "fullwidth"
    center = (x0_norm + x1_norm) / 2
    return "left" if center < COLUMN_SPLIT_RATIO else "right"


def try_find_tables_structured(page: fitz.Page) -> list:
    """
    Intenta extraer tablas con bordes usando find_tables().
    Retorna lista de dicts con título, contenido markdown y bbox.
    """
    results = []
    try:
        tabs = page.find_tables()
        for tab in tabs.tables:
            try:
                df = tab.to_pandas()
                headers = df.columns.tolist()
                rows    = df.values.tolist()

                md_lines = []
                md_lines.append("| " + " | ".join(str(h) for h in headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for row in rows:
                    clean = [str(c).replace("\n", " ").strip() if c is not None else "" for c in row]
                    md_lines.append("| " + " | ".join(clean) + " |")

                results.append({
                    "method":   "structured (find_tables)",
                    "bbox":     tab.bbox,
                    "rows":     tab.row_count,
                    "cols":     tab.col_count,
                    "markdown": "\n".join(md_lines),
                    "preview":  "\n".join(md_lines[:5])
                })
            except Exception as e:
                results.append({
                    "method":   "structured (find_tables) — parse error",
                    "bbox":     tab.bbox,
                    "rows":     getattr(tab, 'row_count', '?'),
                    "cols":     getattr(tab, 'col_count', '?'),
                    "markdown": f"[ERROR parsing table: {e}]",
                    "preview":  f"[ERROR: {e}]"
                })
    except Exception:
        pass
    return results


def find_heuristic_tables(page: fitz.Page) -> list:
    """
    Detecta tablas heurísticamente por patrones de contenido.
    Usado cuando find_tables() no detecta nada.
    Retorna lista de dicts con título, contexto y preview.
    """
    page_width = page.rect.width
    blocks     = sorted(page.get_text("blocks"), key=lambda b: b[1])

    results = []
    i       = 0

    while i < len(blocks):
        block = blocks[i]
        text  = block[4] if block[4] else ""

        if not text.strip():
            i += 1
            continue

        if is_table_block(text):
            # Buscar título hasta 5 bloques atrás
            title = None
            for j in range(i - 1, max(i - 6, -1), -1):
                prev = blocks[j][4].strip() if blocks[j][4] else ""
                if re.match(r"^Table\s+\d+\.\d+", prev):
                    title = prev[:80]
                    break

            if not title:
                title_match = re.search(r"Table\s+\d+\.\d+[^\n]{0,40}", text)
                title = title_match.group(0)[:80] if title_match else "Untitled table"

            block_type = classify_block(block, page_width)
            results.append({
                "method":    "heuristic",
                "title":     title,
                "block_idx": i,
                "y0":        block[1],
                "type":      block_type,
                "preview":   text[:200].replace("\n", " ")
            })

            # Saltar bloques consecutivos de la misma tabla
            while i + 1 < len(blocks):
                next_text = blocks[i + 1][4] if blocks[i + 1][4] else ""
                if is_table_block(next_text):
                    i += 1
                else:
                    break

        i += 1

    return results


def audit_document(pdf_path: Path) -> dict:
    """
    Audita un documento PDF completo.
    Retorna un dict con estadísticas y detalles de todas las tablas encontradas.
    """
    doc          = fitz.open(str(pdf_path))
    total_pages  = len(doc)

    structured_tables  = []
    heuristic_tables   = []
    pages_with_tables  = set()

    for page_num, page in enumerate(doc, start=1):
        # Intentar detección estructurada primero
        struct = try_find_tables_structured(page)
        if struct:
            for t in struct:
                t["page"] = page_num
                structured_tables.append(t)
            pages_with_tables.add(page_num)

        # Detección heurística — siempre ejecutar para comparar
        heur = find_heuristic_tables(page)
        if heur:
            for t in heur:
                t["page"] = page_num
                heuristic_tables.append(t)
            pages_with_tables.add(page_num)

    doc.close()

    return {
        "file":               pdf_path.name,
        "total_pages":        total_pages,
        "pages_with_tables":  len(pages_with_tables),
        "structured_count":   len(structured_tables),
        "heuristic_count":    len(heuristic_tables),
        "structured_tables":  structured_tables,
        "heuristic_tables":   heuristic_tables,
    }


def format_report(audit: dict) -> str:
    """Formatea el reporte de auditoría de un documento."""
    lines = []
    sep   = "=" * 70

    lines.append(sep)
    lines.append(f"DOCUMENTO: {audit['file']}")
    lines.append(sep)
    lines.append(f"  Total páginas          : {audit['total_pages']}")
    lines.append(f"  Páginas con tablas     : {audit['pages_with_tables']}")
    lines.append(f"  Tablas estructuradas   : {audit['structured_count']}  (find_tables — bordes detectables)")
    lines.append(f"  Tablas heurísticas     : {audit['heuristic_count']}  (por patrones de contenido)")
    lines.append("")

    # Recomendación de estrategia
    if audit['structured_count'] > 0:
        lines.append("  ✅ ESTRATEGIA RECOMENDADA: find_tables() — tablas con bordes detectados")
    else:
        lines.append("  ⚠️  ESTRATEGIA RECOMENDADA: Heurística — sin bordes detectables (como ACI 318-19)")
    lines.append("")

    if audit['structured_tables']:
        lines.append("  TABLAS ESTRUCTURADAS DETECTADAS:")
        lines.append("  " + "-" * 50)
        for i, t in enumerate(audit['structured_tables'], 1):
            lines.append(f"\n  [{i}] Página {t['page']} — {t['rows']} filas × {t['cols']} columnas")
            lines.append(f"       Método: {t['method']}")
            lines.append(f"       Preview:")
            for row in t['preview'].split("\n")[:4]:
                lines.append(f"         {row}")

    if audit['heuristic_tables']:
        lines.append("\n  TABLAS HEURÍSTICAS DETECTADAS:")
        lines.append("  " + "-" * 50)
        for i, t in enumerate(audit['heuristic_tables'], 1):
            lines.append(f"\n  [{i}] Página {t['page']} — Bloque tipo '{t['type']}'")
            lines.append(f"       Título: {t['title']}")
            lines.append(f"       Preview: {t['preview'][:120]}...")

    lines.append("")
    return "\n".join(lines)


def main():
    input_path  = Path(DATA_DIR)
    report_path = Path(REPORT_DIR)

    if not input_path.exists():
        print(f"ERROR: Directorio '{DATA_DIR}' no encontrado.")
        return

    report_path.mkdir(exist_ok=True)

    pdf_files = sorted(input_path.glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: No se encontraron PDFs en '{DATA_DIR}'.")
        return

    print(f"Auditando {len(pdf_files)} documentos...")
    print("=" * 70)

    full_report   = []
    summary_lines = ["RESUMEN EJECUTIVO — STACK NORMATIVO FUVIA", "=" * 70, ""]

    for pdf_file in pdf_files:
        print(f"  Procesando: {pdf_file.name}...")
        try:
            audit  = audit_document(pdf_file)
            report = format_report(audit)

            full_report.append(report)

            # Guardar reporte individual por documento
            doc_report_path = report_path / (pdf_file.stem + "_tables.txt")
            doc_report_path.write_text(report, encoding="utf-8")

            # Línea de resumen
            strategy = "find_tables()" if audit['structured_count'] > 0 else "Heurística"
            summary_lines.append(
                f"  {pdf_file.name:<35} "
                f"Estructuradas: {audit['structured_count']:>3}  "
                f"Heurísticas: {audit['heuristic_count']:>3}  "
                f"Estrategia: {strategy}"
            )

        except Exception as e:
            print(f"  ✗ Error en {pdf_file.name}: {e}")
            summary_lines.append(f"  {pdf_file.name:<35} ERROR: {e}")

    # Guardar reporte completo
    summary_lines.append("")
    complete_report = "\n".join(summary_lines) + "\n\n" + "\n".join(full_report)
    report_file     = report_path / "audit_tables.txt"
    report_file.write_text(complete_report, encoding="utf-8")

    print("\n" + "=" * 70)
    print("Auditoría completada.")
    print(f"Reportes guardados en: ./{REPORT_DIR}/")
    print(f"Reporte completo    : ./{REPORT_DIR}/audit_tables.txt")
    print("")
    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()