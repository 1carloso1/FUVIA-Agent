import os
import logging
import chromadb
from dotenv import load_dotenv

from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.anthropic import Anthropic
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import TextNode
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.retrievers.bm25 import BM25Retriever

# Cargar variables de entorno (.env)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CHROMA_DB_DIR = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

def setup_settings():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    # Mantenemos el modelo BGE para la búsqueda semántica
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    # Claude 4.6 Sonnet para el razonamiento
    Settings.llm = Anthropic(model="claude-sonnet-4-6", api_key=api_key)

# --- CLASE CUSTOM PARA LA TESIS: BÚSQUEDA HÍBRIDA ---
class HybridRetriever(BaseRetriever):
    """
    Fusiona Búsqueda Semántica (ChromaDB) con Búsqueda Léxica (BM25).
    Ideal para recuperar conceptos narrativos y tablas con IDs exactos.
    """
    def __init__(self, vector_retriever, bm25_retriever):
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever
        super().__init__()

    def _retrieve(self, query_bundle):
        # 1. Búsqueda Semántica (Entiende el concepto general)
        vector_nodes = self.vector_retriever.retrieve(query_bundle)
        
        # 2. Búsqueda Léxica (Busca palabras/números exactos como "19.2.1.1")
        bm25_nodes = self.bm25_retriever.retrieve(query_bundle)
        
        # 3. Combinar resultados y eliminar duplicados por ID de nodo
        all_nodes = {}
        for n in vector_nodes + bm25_nodes:
            if n.node.node_id not in all_nodes:
                all_nodes[n.node.node_id] = n
                
        return list(all_nodes.values())

def test_rag_pipeline(query_str: str):
    logger.info("Conectando a ChromaDB...")
    db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    chroma_collection = db.get_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    
    # 1. Configurar el Retriever Vectorial (Reducido a 3 para ahorrar tokens/dinero)
    index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
    vector_retriever = index.as_retriever(similarity_top_k=3) 
    
    # 2. Construir el índice BM25 extrayendo el texto directamente de ChromaDB
    #    (Así no gastamos créditos de LlamaParse volviendo a procesar el PDF)
    logger.info("Construyendo índice léxico (BM25) en memoria...")
    chroma_data = chroma_collection.get()
    nodes = []
    for i, doc_text in enumerate(chroma_data['documents']):
        nodes.append(TextNode(text=doc_text, id_=chroma_data['ids'][i]))
    
    # Top 2 para las coincidencias exactas de texto
    bm25_retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=2) 
    
    # 3. Ensamblar el Retriever Híbrido (3 vectoriales + 2 léxicos = Máximo 5 chunks al LLM)
    hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)
    
    # 4. Crear el motor de consulta
    query_engine = RetrieverQueryEngine.from_args(
        retriever=hybrid_retriever,
        llm=Settings.llm
    )
    
    print("\n--- CONSULTANDO AL AGENTE (CLAUDE 4.6 SONNET) ---")
    print(f"Query: '{query_str}'\n")
    
    response = query_engine.query(query_str)
    
    print("🤖 RESPUESTA DEL AGENTE:")
    print(response)
    print("\n📚 FUENTES UTILIZADAS (Híbridas):")
    for i, node in enumerate(response.source_nodes):
        score_str = f"{node.score:.4f}" if node.score is not None else "Lexical/BM25"
        print(f"\n--- NODO {i+1} | ID: {node.node.node_id[:8]}... | Score: {score_str} ---")
        # Imprimimos los primeros 500 caracteres del texto real que vio Claude
        print(node.node.text[:500] + "...\n")

if __name__ == "__main__":
    setup_settings()
    # La consulta ahora está optimizada para que BM25 atrape la tabla
    test_query = "What is the minimum specified compressive strength (f'c) for concrete used in special seismic systems? Look specifically for Table 19.2.1.1. State the value in psi and MPa if available."
    test_rag_pipeline(test_query)