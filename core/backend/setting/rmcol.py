"""qdrant 컬렉션 확인"""

from qdrant_client import QdrantClient
from core.config import QDRANT_URL, QDRANT_API_KEY


client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY
)

print(client.get_collections())
