import json
import os
import requests
from qdrant_client import QdrantClient, models
from qdrant_client.http.models import Distance
from tqdm import tqdm
import sys 

# -----------------------------
# 1. 설정 및 상수
# -----------------------------

from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY, SOLAR_API_KEY

# Upstage API 설정
UPSTAGE_EMBEDDING_ENDPOINT = "https://api.upstage.ai/v1/embeddings"
EMBEDDING_MODEL = "embedding-passage"
BATCH_SIZE = 100 
VECTOR_DIMENSION = 4096 # Upstage Embeddings 모델 차원

# -----------------------------
# 2. Upstage Embeddings API 호출 함수 (유지)
# -----------------------------

def get_upstage_embeddings(texts: list) -> list:
    """
    Upstage Embeddings API를 호출하여 텍스트 리스트의 임베딩을 배치 처리합니다.
    """
    headers = {
        "Authorization": f"Bearer {SOLAR_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": EMBEDDING_MODEL,
        "input": texts
    }

    try:
        response = requests.post(
            UPSTAGE_EMBEDDING_ENDPOINT,
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        
        embeddings = [item['embedding'] for item in response.json().get('data', [])]
        return embeddings
        
    except requests.exceptions.HTTPError as err:
        print(f"\n  [API Error] HTTP 오류 발생: {err}", file=sys.stderr)
        print(f"  [API Response] {response.text}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"\n  [API Error] 알 수 없는 오류: {e}", file=sys.stderr)
        return []

# -----------------------------
# 3. 메인 색인 파이프라인 (Payload 로직 수정)
# -----------------------------

def run_indexing_pipeline():
    """
    임시 JSON 파일을 읽고 Qdrant에 벡터를 색인하는 메인 파이프라인.
    명령줄 인자: [1] JSON 파일 경로, [2] 시작 Qdrant ID
    """
    
    # 1. 인자 받기
    if len(sys.argv) < 3:
        print(f"오류: JSON 파일 경로와 시작 Qdrant ID가 필요합니다.", file=sys.stderr)
        sys.exit(1)
        
    SINGLE_JSON_FILE_PATH = sys.argv[1]
    STARTING_GLOBAL_ID = int(sys.argv[2]) 
    
    # Qdrant 클라이언트 초기화 
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    
    # A. 단일 JSON 파일 로드
    all_chunks = []
    try:
        with open(SINGLE_JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            all_chunks = json.load(f)
        print(f"[로딩] 임시 JSON 로드 성공. (총 {len(all_chunks)} 청크, 시작 ID: {STARTING_GLOBAL_ID})", file=sys.stderr)
    except Exception as e:
        print(f"[오류] JSON 로드 실패: {e}", file=sys.stderr)
        sys.exit(1)

    # B. 컬렉션 존재 확인
    if not qdrant_client.collection_exists(collection_name=COLLECTION_NAME):
        print(f"[오류] 컬렉션 '{COLLECTION_NAME}'을(를) 찾을 수 없습니다. 컬렉션 생성 스크립트를 먼저 실행하세요.", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n[색인 준비] 총 {len(all_chunks)}개 청크 처리 시작.", file=sys.stderr)

    # C. 배치 임베딩 및 Qdrant 색인
    total_chunks = len(all_chunks)
    
    for i in tqdm(range(0, total_chunks, BATCH_SIZE), desc="배치 임베딩 및 색인 진행", file=sys.stderr):
        batch_chunks = all_chunks[i:i + BATCH_SIZE]
        texts_to_embed = [chunk['text_for_embedding'] for chunk in batch_chunks]
        
        # 1. 임베딩 벡터 생성
        batch_vectors = get_upstage_embeddings(texts_to_embed)
        
        if not batch_vectors:
            print(f"\n[경고] 배치 {i} ~ {i + len(batch_chunks)-1} 임베딩 생성 실패. 건너뜀.", file=sys.stderr)
            continue

        # 2. 고유 ID 생성 (중앙 로직이 전달한 시작 ID를 기반으로)
        start_id = STARTING_GLOBAL_ID + i 
        batch_ids = list(range(start_id, start_id + len(batch_vectors))) 
        
        # 3. Qdrant Payload 준비 (summary 필드 추가)
        batch_payloads = []
        for chunk in batch_chunks:
            payload = {
                "doc_id": chunk['doc_id'],
                "page_number": chunk['page'],
                "chunk_in_page": chunk['chunk_in_page'],
                "text_for_embedding": chunk['text_for_embedding'],
                "summary": chunk.get('summary', '요약 없음') # 💡 summary 필드 추가
            }
            batch_payloads.append(payload)

        # 4. Qdrant에 데이터 일괄 삽입
        try:
            qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                points=models.Batch(
                    vectors=batch_vectors,
                    payloads=batch_payloads,
                    ids=batch_ids, 
                ),
                wait=True 
            )
        except Exception as e:
            print(f"\n[Qdrant Error] 배치 색인 실패: {e}", file=sys.stderr)
            sys.exit(1)
            
    print(f"\n\n[파이프라인 완료] 총 {total_chunks}개 청크 Qdrant 색인 완료.", file=sys.stderr)
    
    # 5. 처리 완료 신호
    print("EMBEDDING_SUCCESS") 


if __name__ == "__main__":
    run_indexing_pipeline()