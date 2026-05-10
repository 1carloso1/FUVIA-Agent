import os
import logging
import chromadb
from dotenv import load_dotenv
from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    Settings
)
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_parse import LlamaParse  # <-- Nuevo import

# Cargar variables de entorno (.env)
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATA_DIR = "./data"
CHROMA_DB_DIR = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

def setup_settings():
    logger.info("Configurando el modelo de embeddings (HuggingFace)...")
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    Settings.llm = None  
    # Aumentamos un poco el chunk_size para no cortar las tablas a la mitad
    Settings.chunk_size = 1024 
    Settings.chunk_overlap = 100

def ingest_documents():
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        logger.error("No se encontró LLAMA_CLOUD_API_KEY en el archivo .env")
        return

    if not os.path.exists(DATA_DIR) or not os.listdir(DATA_DIR):
        logger.error(f"El directorio '{DATA_DIR}' no existe o está vacío.")
        return

    setup_settings()

    logger.info("Cargando documentos usando LlamaParse (Extracción de Tablas a Markdown)...")
    
    # Configurar el parser avanzado
    parser = LlamaParse(
        result_type="markdown",  # Instruye a LlamaParse a formatear tablas como Markdown
        verbose=True
    )
    
    file_extractor = {".pdf": parser}
    
    documents = SimpleDirectoryReader(
        DATA_DIR, 
        file_extractor=file_extractor
    ).load_data()
    
    logger.info(f"Se extrajeron {len(documents)} bloques de contenido.")

    logger.info("Inicializando ChromaDB client...")
    db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
    chroma_collection = db.get_or_create_collection(COLLECTION_NAME)
    
    logger.info("Configurando el Vector Store y Storage Context...")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    logger.info("Generando embeddings e indexando. Esto puede tomar unos minutos...")
    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context
    )
    
    logger.info(f"Ingesta completada con éxito en {CHROMA_DB_DIR}.")

if __name__ == "__main__":
    ingest_documents()