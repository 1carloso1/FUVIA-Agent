import os
import logging
import chromadb
from pathlib import Path
from dotenv import load_dotenv
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings
)
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_parse import LlamaParse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DATA_DIR = "./data"
CHROMA_DB_DIR = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

# Metadata explícita por archivo.
# Agrega aquí cada PDF del stack normativo con su norma, versión y capítulos indexados.
# Esto permite que el agente cite la fuente correcta en el reporte técnico.
DOCUMENT_METADATA = {
    "ACI_211.1-22.pdf": {
        "standard": "ACI 211.1-22",
        "organization": "ACI",
        "topic": "Normal concrete mix proportioning",
        "chapters_indexed": "1-9",
        "priority": "high"
    },
    "ACI_211.4R-08.pdf": {
        "standard": "ACI 211.4R-08",
        "organization": "ACI",
        "topic": "High-strength concrete mix proportioning",
        "chapters_indexed": "1-8",
        "priority": "high"
    },
    "ACI_318-19_selected.pdf": {
        "standard": "ACI 318-19",
        "organization": "ACI",
        "topic": "Structural concrete requirements and durability",
        "chapters_indexed": "2, 9, 10, 18, 19, 26",
        "priority": "high"
    },
    "ASTM_C150-22.pdf": {
        "standard": "ASTM C150/C150M-22",
        "organization": "ASTM",
        "topic": "Portland cement specifications",
        "chapters_indexed": "complete",
        "priority": "high"
    },
    "ASTM_C33-13.pdf": {
        "standard": "ASTM C33/C33M-13",
        "organization": "ASTM",
        "topic": "Concrete aggregates specifications",
        "chapters_indexed": "complete",
        "priority": "high"
    },
    "ASTM_C494-19.pdf": {
        "standard": "ASTM C494/C494M-19",
        "organization": "ASTM",
        "topic": "Chemical admixtures for concrete",
        "chapters_indexed": "complete",
        "priority": "high"
    },
}


def setup_settings():
    """
    Configura el modelo de embeddings para la fase de ingesta.
    LLM se deshabilita explícitamente aquí porque la ingesta no requiere
    generación de texto — solo conversión de chunks a vectores.
    Si necesitas el LLM en otro módulo, configúralo allí independientemente.
    """
    logger.info("Configurando modelo de embeddings: BAAI/bge-small-en-v1.5")
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    Settings.llm = None
    # chunk_size=1024 evita cortar tablas técnicas a la mitad.
    # chunk_overlap=150 asegura continuidad entre chunks para cláusulas multi-párrafo.
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 150


def get_already_indexed_files(chroma_collection) -> set:
    """
    Retorna el conjunto de nombres de archivo ya indexados en ChromaDB.
    Previene duplicados si el script se ejecuta múltiples veces.
    """
    try:
        results = chroma_collection.get(include=["metadatas"])
        indexed = set()
        for metadata in results["metadatas"]:
            if metadata and "source_file" in metadata:
                indexed.add(metadata["source_file"])
        return indexed
    except Exception as e:
        logger.warning(f"No se pudo verificar archivos ya indexados: {e}")
        return set()


def build_parser() -> LlamaParse:
    """
    Configura LlamaParse con instrucciones específicas para documentos
    técnicos de ingeniería. Las instrucciones guían al parser a priorizar
    tablas de dosificación, fórmulas y referencias normativas.
    """
    return LlamaParse(
        result_type="markdown",
        parsing_instruction=(
            "This is a technical civil engineering standards document (ACI or ASTM). "
            "Preserve all tables in markdown format — they contain critical mix design data. "
            "Preserve all equations and formulas with their variable definitions. "
            "Preserve section and clause numbers exactly as they appear (e.g., 19.3.2, Table 26.4.2.1). "
            "Do not summarize or paraphrase any content. Extract text verbatim."
        ),
        verbose=True
    )


def ingest_documents():
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        logger.error("LLAMA_CLOUD_API_KEY no encontrada en .env — abortando.")
        return

    data_path = Path(DATA_DIR)
    if not data_path.exists() or not any(data_path.iterdir()):
        logger.error(f"Directorio '{DATA_DIR}' no existe o está vacío.")
        return

    setup_settings()

    # Inicializar ChromaDB y verificar duplicados ANTES de parsear
    logger.info("Inicializando ChromaDB...")
    db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    chroma_collection = db.get_or_create_collection(COLLECTION_NAME)

    already_indexed = get_already_indexed_files(chroma_collection)
    if already_indexed:
        logger.info(f"Archivos ya indexados (se omitirán): {already_indexed}")

    # Filtrar solo PDFs no indexados aún
    pdf_files = list(data_path.glob("*.pdf"))
    pending_files = [f for f in pdf_files if f.name not in already_indexed]

    if not pending_files:
        logger.info("Todos los documentos ya están indexados. Nada que procesar.")
        return

    logger.info(f"Documentos pendientes de indexar: {[f.name for f in pending_files]}")

    parser = build_parser()
    file_extractor = {".pdf": parser}

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Procesar cada documento individualmente para aislar errores
    for pdf_file in pending_files:
        logger.info(f"Procesando: {pdf_file.name}")
        try:
            # Obtener metadata del documento o usar valores por defecto
            doc_metadata = DOCUMENT_METADATA.get(pdf_file.name, {
                "standard": pdf_file.stem,
                "organization": "unknown",
                "topic": "unknown",
                "chapters_indexed": "complete",
                "priority": "medium"
            })
            # Agregar nombre de archivo a la metadata para control de duplicados
            doc_metadata["source_file"] = pdf_file.name

            documents = SimpleDirectoryReader(
                input_files=[str(pdf_file)],
                file_extractor=file_extractor,
                file_metadata=lambda _: doc_metadata
            ).load_data()

            logger.info(f"  → {len(documents)} chunks extraídos de {pdf_file.name}")

            VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context
            )

            logger.info(f"  ✓ {pdf_file.name} indexado correctamente")

        except Exception as e:
            # Error aislado por documento — el resto del stack sigue procesándose
            logger.error(f"  ✗ Error procesando {pdf_file.name}: {e}")
            logger.error("  → Documento omitido. El resto del stack continúa.")
            continue

    logger.info(f"Ingesta finalizada. Base vectorial disponible en: {CHROMA_DB_DIR}")
    logger.info(f"Colección: '{COLLECTION_NAME}'")


if __name__ == "__main__":
    ingest_documents()