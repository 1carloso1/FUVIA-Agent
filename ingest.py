import os
import logging
import chromadb
from pathlib import Path
from dotenv import load_dotenv
from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    Settings,
    Document
)
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_CLEAN_DIR  = "./data_clean"
CHROMA_DB_DIR   = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

# Metadata base por documento
# El número de página se agrega dinámicamente desde el header del .txt
DOCUMENT_METADATA = {
    "ACI_211.1-22": {
        "standard":         "ACI 211.1-22",
        "organization":     "ACI",
        "topic":            "Normal concrete mix proportioning",
        "chapters_indexed": "1-9",
    },
    "ACI_211.4R-08": {
        "standard":         "ACI 211.4R-08",
        "organization":     "ACI",
        "topic":            "High-strength concrete mix proportioning",
        "chapters_indexed": "1-8",
    },
    "ACI_318-19_selected": {
        "standard":         "ACI 318-19",
        "organization":     "ACI",
        "topic":            "Structural concrete requirements and durability",
        "chapters_indexed": "2, 9, 10, 18, 19, 26",
    },
    "ASTM_C150-22": {
        "standard":         "ASTM C150/C150M-22",
        "organization":     "ASTM",
        "topic":            "Portland cement specifications",
        "chapters_indexed": "complete",
    },
    "ASTM_C33-13": {
        "standard":         "ASTM C33/C33M-13",
        "organization":     "ASTM",
        "topic":            "Concrete aggregates specifications",
        "chapters_indexed": "complete",
    },
    "ASTM_C494-19": {
        "standard":         "ASTM C494/C494M-19",
        "organization":     "ASTM",
        "topic":            "Chemical admixtures for concrete",
        "chapters_indexed": "complete",
    },
}


def setup_settings():
    """
    Configura embeddings para ingesta.
    LLM deshabilitado — la ingesta solo necesita vectorización.
    """
    logger.info("Configurando modelo de embeddings: BAAI/bge-small-en-v1.5")
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    Settings.llm  = None
    # chunk_size alto porque cada .txt es una sola página —
    # queremos que cada página sea idealmente un solo chunk
    Settings.chunk_size    = 2048
    Settings.chunk_overlap = 100


def get_already_indexed(chroma_collection) -> set:
    """
    Retorna conjunto de source_ids ya indexados.
    Formato: "document_name/page_001"
    """
    try:
        results = chroma_collection.get(include=["metadatas"])
        indexed = set()
        for meta in results["metadatas"]:
            if meta and "source_id" in meta:
                indexed.add(meta["source_id"])
        return indexed
    except Exception as e:
        logger.warning(f"No se pudo verificar archivos indexados: {e}")
        return set()


def parse_page_header(content: str) -> dict:
    """
    Extrae metadata del header generado por preprocess_master.py.
    Header formato:
        [DOCUMENT: ACI_318-19_selected]
        [PAGE: 137/196]
        [LAYOUT: CODE/COMMENTARY]
    """
    import re
    metadata = {}

    doc_match    = re.search(r"\[DOCUMENT: ([^\]]+)\]", content)
    page_match   = re.search(r"\[PAGE: (\d+)/(\d+)\]", content)
    layout_match = re.search(r"\[LAYOUT: ([^\]]+)\]", content)

    if doc_match:
        metadata["document"] = doc_match.group(1)
    if page_match:
        metadata["page"]        = int(page_match.group(1))
        metadata["total_pages"] = int(page_match.group(2))
    if layout_match:
        metadata["layout"] = layout_match.group(1)

    return metadata


def load_document_pages(doc_dir: Path, base_metadata: dict,
                        already_indexed: set) -> list:
    """
    Carga todas las páginas de un documento como Documents de LlamaIndex.
    Cada página .txt se convierte en un Document independiente con
    metadata completa incluyendo número de página.
    """
    txt_files = sorted(doc_dir.glob("page_*.txt"))
    documents = []

    for txt_file in txt_files:
        content = txt_file.read_text(encoding="utf-8")

        # Extraer metadata del header
        page_meta = parse_page_header(content)
        page_num  = page_meta.get("page", 0)
        doc_name  = page_meta.get("document", doc_dir.name)

        source_id = f"{doc_name}/page_{page_num:03d}"

        # Saltar si ya está indexado
        if source_id in already_indexed:
            continue

        # Remover el header del contenido — no aporta al RAG
        body = content.split("=" * 60)[-1].strip() if "=" * 60 in content else content

        if len(body) < 50:
            continue

        # Construir metadata completa para citación exacta
        metadata = {
            **base_metadata,
            "page":       page_num,
            "source_id":  source_id,
            "layout":     page_meta.get("layout", "continuous"),
            "source_file": doc_dir.name,
        }

        documents.append(Document(text=body, metadata=metadata))

    return documents


def ingest_documents():
    data_clean_path = Path(DATA_CLEAN_DIR)

    if not data_clean_path.exists():
        logger.error(
            f"Directorio '{DATA_CLEAN_DIR}' no encontrado. "
            "Ejecuta preprocess_master.py primero."
        )
        return

    # Verificar que existen subcarpetas con páginas
    doc_dirs = [d for d in data_clean_path.iterdir() if d.is_dir()]
    if not doc_dirs:
        logger.error(
            f"No se encontraron subcarpetas en '{DATA_CLEAN_DIR}'. "
            "Ejecuta preprocess_master.py primero."
        )
        return

    setup_settings()

    logger.info("Inicializando ChromaDB...")
    db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    chroma_collection = db.get_or_create_collection(COLLECTION_NAME)

    already_indexed = get_already_indexed(chroma_collection)
    if already_indexed:
        logger.info(f"Páginas ya indexadas: {len(already_indexed)}")

    vector_store    = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    total_pages   = 0
    total_skipped = 0

    for doc_dir in sorted(doc_dirs):
        doc_name      = doc_dir.name
        base_metadata = DOCUMENT_METADATA.get(doc_name, {
            "standard":         doc_name,
            "organization":     "unknown",
            "topic":            "unknown",
            "chapters_indexed": "complete",
        })

        logger.info(f"Procesando: {doc_name}")

        try:
            documents = load_document_pages(
                doc_dir, base_metadata, already_indexed
            )

            if not documents:
                logger.info(f"  → Sin páginas nuevas en {doc_name}")
                total_skipped += 1
                continue

            logger.info(f"  → {len(documents)} páginas a indexar")

            VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context
            )

            total_pages += len(documents)
            logger.info(f"  ✓ {doc_name} indexado correctamente")

        except Exception as e:
            logger.error(f"  ✗ Error indexando {doc_name}: {e}")
            continue

    logger.info(f"\nIngesta finalizada.")
    logger.info(f"  Páginas indexadas : {total_pages}")
    logger.info(f"  Docs sin cambios  : {total_skipped}")
    logger.info(f"  Colección         : '{COLLECTION_NAME}'")
    logger.info(f"  Base vectorial    : {CHROMA_DB_DIR}")


if __name__ == "__main__":
    ingest_documents()