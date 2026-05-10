import chromadb

CHROMA_DB_DIR = "./chroma_db"
COLLECTION_NAME = "aci_astm_standards"

print("Escaneando toda la base de datos documento por documento...")
db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
collection = db.get_collection(COLLECTION_NAME)
data = collection.get()

found = False
for i, doc in enumerate(data['documents']):
    # Buscamos variaciones posibles por si LlamaParse metió espacios
    if "19.2.1.1" in doc or "19. 2. 1. 1" in doc:
        print(f"\n✅ ¡ENCONTRADO EN NODO ID: {data['ids'][i]}!")
        print("-" * 50)
        # Imprimimos los primeros 1000 caracteres de ese chunk
        print(doc[:1000]) 
        print("-" * 50)
        found = True

if not found:
    print("\n❌ ¡ALERTA ROJA! La cadena '19.2.1.1' no existe en toda tu base de datos.")
    print(f"Total de fragmentos revisados: {len(data['documents'])}")