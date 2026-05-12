import os
import logging
import chromadb
from dotenv import load_dotenv

from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.prompts import PromptTemplate
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.anthropic import Anthropic
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import TextNode
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.retrievers.bm25 import BM25Retriever

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CHROMA_DB_DIR = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

# --- PROMPT DE SISTEMA ---
# Instruye a Claude a comportarse como asistente normativo de ingeniería civil.
# Reemplaza el prompt genérico de LlamaIndex.
NORMATIVE_QA_PROMPT = PromptTemplate(
    "You are a technical assistant specialized in ACI and ASTM standards for "
    "concrete mix design and structural requirements. "
    "Your answers must be precise, cite specific clause numbers when available, "
    "and never extrapolate beyond what the provided normative context states.\n\n"
    "If the context does not contain enough information to answer the question, "
    "explicitly state which standard or clause would be needed.\n\n"
    "Context from normative documents:\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n\n"
    "Question: {query_str}\n\n"
    "Answer (cite clause numbers and standard names):"
)


def validate_environment() -> bool:
    """
    Valida variables de entorno al inicio.
    Falla rápido antes de gastar tiempo en retrieval si falta configuración.
    """
    missing = []
    if not os.getenv("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        missing.append("LLAMA_CLOUD_API_KEY")
    if missing:
        logger.error(f"Variables de entorno faltantes: {missing}")
        return False
    return True


def setup_settings():
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    Settings.llm = Anthropic(
        model="claude-sonnet-4-6",
        api_key=os.getenv("ANTHROPIC_API_KEY")
    )


class HybridRetriever(BaseRetriever):
    """
    Fusiona búsqueda semántica (ChromaDB) con búsqueda léxica (BM25).
    - Semántica: recupera conceptos y requisitos narrativos
    - BM25: recupera cláusulas y tablas por número exacto (ej. "19.3.2", "Table 4.3.3")
    """
    def __init__(self, vector_retriever, bm25_retriever):
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever
        super().__init__()

    def _retrieve(self, query_bundle):
        vector_nodes = self.vector_retriever.retrieve(query_bundle)
        bm25_nodes = self.bm25_retriever.retrieve(query_bundle)

        # Deduplicar por node_id — un chunk no debe aparecer dos veces
        seen = {}
        for node in vector_nodes + bm25_nodes:
            if node.node.node_id not in seen:
                seen[node.node.node_id] = node

        return list(seen.values())


def format_source(node, index: int) -> str:
    """
    Formatea una fuente recuperada usando la metadata indexada en ingest.py.
    Si la metadata no existe (documento indexado sin ella), muestra fallback limpio.
    """
    metadata = node.node.metadata or {}

    standard    = metadata.get("standard", "Unknown standard")
    topic       = metadata.get("topic", "N/A")
    chapters    = metadata.get("chapters_indexed", "N/A")
    source_file = metadata.get("source_file", "N/A")

    # Score: numérico para semántico, etiqueta para BM25
    if node.score is not None:
        score_display = f"Semantic score: {node.score:.4f}"
    else:
        score_display = "Lexical match (BM25)"

    # Preview del chunk — primeros 400 caracteres
    text_preview = node.node.text[:400].replace("\n", " ").strip()
    if len(node.node.text) > 400:
        text_preview += "..."

    return (
        f"\n  [{index}] {standard}\n"
        f"      Topic    : {topic}\n"
        f"      Chapters : {chapters}\n"
        f"      File     : {source_file}\n"
        f"      Retrieval: {score_display}\n"
        f"      Preview  : {text_preview}\n"
    )


def run_query(query_str: str):
    logger.info("Conectando a ChromaDB...")
    db = chromadb.PersistentClient(path=CHROMA_DB_DIR)

    try:
        chroma_collection = db.get_collection(COLLECTION_NAME)
    except Exception:
        logger.error(
            f"Colección '{COLLECTION_NAME}' no encontrada. "
            "Ejecuta ingest.py primero."
        )
        return

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    # Retriever semántico — top 3 por similitud conceptual
    index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
    vector_retriever = index.as_retriever(similarity_top_k=3)

    # Retriever BM25 — construido desde ChromaDB con metadata preservada
    logger.info("Construyendo índice BM25 en memoria...")
    chroma_data = chroma_collection.get(include=["documents", "metadatas"])

    nodes = []
    for doc_text, metadata, doc_id in zip(
        chroma_data["documents"],
        chroma_data["metadatas"],
        chroma_data["ids"]
    ):
        nodes.append(
            TextNode(
                text=doc_text,
                id_=doc_id,
                metadata=metadata or {}  # FIX: metadata preservada en BM25
            )
        )

    bm25_retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=2)

    hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)

    # Query engine con prompt normativo especializado
    query_engine = RetrieverQueryEngine.from_args(
        retriever=hybrid_retriever,
        llm=Settings.llm,
        text_qa_template=NORMATIVE_QA_PROMPT
    )

    print(f"\n{'─'*60}")
    print(f"  QUERY: {query_str}")
    print(f"{'─'*60}\n")

    response = query_engine.query(query_str)

    print("RESPUESTA NORMATIVA:")
    print(f"{response}\n")

    print(f"{'─'*60}")
    print(f"  FUENTES CONSULTADAS ({len(response.source_nodes)} chunks)")
    print(f"{'─'*60}")

    for i, node in enumerate(response.source_nodes, start=1):
        print(format_source(node, i))


if __name__ == "__main__":
    if not validate_environment():
        exit(1)

    setup_settings()

    print("\n" + "=" * 60)
    print("  FUVIA RAG — TERMINAL DE PRUEBAS NORMATIVAS")
    print("  Stack: ACI 211.1 · ACI 211.4R · ACI 318-19 · ASTM C150/C33/C494")
    print("  Escribe 'exit' para salir.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_query = input("Pregunta> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCerrando terminal...")
            break

        if not user_query:
            continue

        if user_query.lower() in ["exit", "salir", "quit"]:
            print("Cerrando terminal...")
            break

        print("\nRecuperando del stack normativo...\n")
        run_query(user_query)
        print()