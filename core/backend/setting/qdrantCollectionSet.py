"""이 파일은 qdrant에 컬렉션을 생성하는 설정 코드"""

import os
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import Distance, VectorParams

from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY



# Upstage Solar Embedding 모델 설정
VECTOR_DIMENSION = 4096 # Upstage Embeddings 모델의 차원 수
VECTOR_DISTANCE = Distance.COSINE # 코사인 유사도 사용

# -----------------------------
# 2. 컬렉션 생성 함수
# -----------------------------

def create_qdrant_collection():
    """
    Qdrant 클라이언트를 초기화하고 'rag_document_chunks' 컬렉션을 생성합니다.
    """
    try:
        client = QdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY # <--- [수정] API 키 인자 추가
        )
        print(f"[Qdrant] Qdrant 서버 연결 확인: {QDRANT_URL}")
        # 기존 컬렉션이 있다면 삭제하고 새로 생성 (테스트 환경에서 안전성을 위해)
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            # 벡터 설정: 차원 4096 및 코사인 유사도 지정
            vectors_config=VectorParams(
                size=VECTOR_DIMENSION, 
                distance=VECTOR_DISTANCE
            )
        )
        print(f"\n✅ 컬렉션 '{COLLECTION_NAME}' 생성 완료.")
        print(f"   > 차원: {VECTOR_DIMENSION}")
        print(f"   > 거리 측정 방식: {VECTOR_DISTANCE.value}")

    except Exception as e:
        print(f"\n❌ [Qdrant Error] 컬렉션 생성 실패. Qdrant 서버가 실행 중인지 확인하십시오.")
        print(f"   오류 내용: {e}")
        
# -----------------------------
# 3. 실행
# -----------------------------
if __name__ == "__main__":
    create_qdrant_collection()