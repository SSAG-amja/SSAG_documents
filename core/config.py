# core/config.py
import os
from dotenv import load_dotenv

# .env에서 환경변수 로드
load_dotenv()

# ---------- Upstage ----------
SOLAR_API_KEY = os.getenv("SOLAR_API_KEY")

# Upstage Embedding 엔드포인트 & 모델
UPSTAGE_EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
UPSTAGE_EMBEDDING_MODEL = "solar-embedding-1-large-passage"

# ---------- Qdrant ----------
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "ssag_documents")
QDRANT_URL = os.getenv("QDRANT_URL") 
COLLECTION_NAME = os.getenv("COLLECTION_NAME") 
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") 



# ---------- MySQL ----------
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
