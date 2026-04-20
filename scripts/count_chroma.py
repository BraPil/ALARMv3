# scripts/count_chroma.py
# Counts vectors in Chroma persistent client path
import os
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "./out/rag_db"

print(f"Counting vectors in Chroma DB at: {path}")

if not os.path.exists(path):
    print(f"ERROR: Path does not exist: {path}")
    sys.exit(1)

# Check if it's a directory
if not os.path.isdir(path):
    print(f"ERROR: Path is not a directory: {path}")
    sys.exit(1)

# Try to connect to Chroma and count vectors
try:
    import chromadb
    
    print(f"Loading Chroma client from {path}...")
    client = chromadb.PersistentClient(path=path)
    
    # List all collections
    collections = client.list_collections()
    
    if not collections:
        print("No collections found in the database")
        sys.exit(0)
    
    print(f"\nFound {len(collections)} collection(s):")
    
    total_vectors = 0
    for collection in collections:
        count = collection.count()
        total_vectors += count
        print(f"  - {collection.name}: {count} vectors")
    
    print(f"\nTotal vectors across all collections: {total_vectors}")
    
    # Get database size
    db_size = 0
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            db_size += os.path.getsize(file_path)
    
    db_size_mb = db_size / (1024 * 1024)
    print(f"Database size: {db_size_mb:.2f} MB")
    
except ImportError:
    print("ERROR: chromadb package not installed. Run: pip install chromadb")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Failed to count vectors: {e}")
    sys.exit(1)
