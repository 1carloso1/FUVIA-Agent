"""
audit_tables.py
===============
Auditor de tablas para el stack normativo FUVIA.
Lee los .txt generados por preprocess_master.py y produce
un índice completo de todas las tablas detectadas por documento.

USO:
    python audit_tables.py

PREREQUISITO:
    Haber ejecutado preprocess_master.py primero.

OUTPUT:
    Consola: resumen ejecutivo por documento
    ./audit_report/audit_index.txt: índice completo exportable
"""

import re
from pathlib import Path

DATA_CLEAN_DIR = "./data_clean"
REPORT_DIR     = "./audit_report"


def audit_document(doc_dir: Path) -> dict:
    """
    Audita todas las páginas de un documento y retorna
    un índice completo de tablas detectadas.
    """
    txt_files   = sorted(doc_dir.glob("page_*.txt"))
    tables      = []
    total_pages = len(txt_files)
    cc_pages    = 0
    empty_pages = 0

    for txt_file in txt_files:
        content = txt_file.read_text(encoding="utf-8")

        page_match = re.search(r"\[PAGE: (\d+)/\d+\]", content)
        page_num   = int(page_match.group(1)) if page_match else 0

        layout_match = re.search(r"\[LAYOUT: ([^\]]+)\]", content)
        layout       = layout_match.group(1) if layout_match else "unknown"
        if "CODE" in layout:
            cc_pages += 1

        body = content.split("=" * 60)[-1] if "=" * 60 in content else content
        if not body.strip():
            empty_pages += 1
            continue

        table_blocks = re.findall(
            r"\[TABLE: ([^\]]+)\]\s*\[TABLE_CONTEXT: ([^\]]+)\]",
            body
        )

        for title, context in table_blocks:
            is_generic = title.startswith("Normative") or title.startswith("Untitled")
            tables.append({
                "page":       page_num,
                "title":      title,
                "context":    context,
                "is_generic": is_generic,
                "file":       txt_file.name,
            })

    real_titles    = [t for t in tables if not t["is_generic"]]
    generic_titles = [t for t in tables if t["is_generic"]]

    return {
        "document":       doc_dir.name,
        "total_pages":    total_pages,
        "cc_pages":       cc_pages,
        "empty_pages":    empty_pages,
        "total_tables":   len(tables),
        "real_titles":    len(real_titles),
        "generic_titles": len(generic_titles),
        "tables":         tables,
    }


def format_document_report(audit: dict) -> str:
    sep   = "=" * 65
    lines = []

    lines.append(sep)
    lines.append(f"  {audit['document']}")
    lines.append(sep)
    lines.append(f"  Páginas totales         : {audit['total_pages']}")
    lines.append(f"  Páginas CODE/COMMENTARY : {audit['cc_pages']}")
    lines.append(f"  Páginas vacías          : {audit['empty_pages']}")
    lines.append(f"  Tablas detectadas       : {audit['total_tables']}")
    lines.append(f"  Tablas con título real  : {audit['real_titles']}")
    lines.append(f"  Tablas título genérico  : {audit['generic_titles']}")

    if audit["total_tables"] == 0:
        lines.append("\n  ⚠️  Sin tablas detectadas — verificar manualmente")
        return "\n".join(lines)

    quality = audit["real_titles"] / audit["total_tables"] * 100
    icon    = "✅" if quality >= 60 else "⚠️ "
    lines.append(f"\n  {icon} Calidad de títulos: {quality:.0f}%")

    lines.append("\n  ÍNDICE DE TABLAS:")
    lines.append("  " + "-" * 55)

    for i, table in enumerate(audit["tables"], 1):
        status  = "✅" if not table["is_generic"] else "⚠️ "
        context = (
            table["context"][:80] + "..."
            if len(table["context"]) > 80
            else table["context"]
        )
        lines.append(f"\n  {status} [{i}] Página {table['page']:>3} — {table['title']}")
        lines.append(f"       Contexto: {context}")

    return "\n".join(lines)


def main():
    data_clean_path = Path(DATA_CLEAN_DIR)
    report_path     = Path(REPORT_DIR)

    if not data_clean_path.exists():
        print(f"ERROR: '{DATA_CLEAN_DIR}' no encontrado.")
        print("Ejecuta preprocess_master.py primero.")
        return

    doc_dirs = sorted([d for d in data_clean_path.iterdir() if d.is_dir()])
    if not doc_dirs:
        print(f"ERROR: No se encontraron subcarpetas en '{DATA_CLEAN_DIR}'.")
        return

    report_path.mkdir(exist_ok=True)

    print(f"\nAuditando {len(doc_dirs)} documentos...\n")

    all_reports   = []
    summary_lines = [
        "ÍNDICE DE TABLAS — STACK NORMATIVO FUVIA",
        "=" * 65,
        "",
        f"  {'Documento':<35} {'Total':>5}  {'Reales':>6}  {'Genér.':>6}  Calidad",
        "  " + "-" * 58,
    ]

    total_tables  = 0
    total_real    = 0
    total_generic = 0

    for doc_dir in doc_dirs:
        audit  = audit_document(doc_dir)
        report = format_document_report(audit)

        all_reports.append(report)
        print(report)
        print()

        doc_report = report_path / f"{doc_dir.name}_audit.txt"
        doc_report.write_text(report, encoding="utf-8")

        total  = audit["total_tables"]
        real   = audit["real_titles"]
        gen    = audit["generic_titles"]
        qual   = f"{real/total*100:.0f}%" if total > 0 else "N/A"

        summary_lines.append(
            f"  {audit['document']:<35} {total:>5}  {real:>6}  {gen:>6}  {qual}"
        )

        total_tables  += total
        total_real    += real
        total_generic += gen

    total_qual = f"{total_real/total_tables*100:.0f}%" if total_tables > 0 else "N/A"
    summary_lines.append("  " + "-" * 58)
    summary_lines.append(
        f"  {'TOTAL':<35} {total_tables:>5}  {total_real:>6}  {total_generic:>6}  {total_qual}"
    )
    summary_lines.append("")
    summary_lines.append("  ✅ Título real    = extraído del documento (ej. 'Table 19.3.2.1')")
    summary_lines.append("  ⚠️  Título genérico = lookback no encontró título — verificar")

    full_report = "\n".join(summary_lines) + "\n\n" + "\n\n".join(all_reports)
    index_file  = report_path / "audit_index.txt"
    index_file.write_text(full_report, encoding="utf-8")

    print("\n" + "=" * 65)
    print("\n".join(summary_lines))
    print(f"\nReporte completo: ./{REPORT_DIR}/audit_index.txt")
    print(f"Reportes por doc: ./{REPORT_DIR}/<documento>_audit.txt")


if __name__ == "__main__":
    main()
