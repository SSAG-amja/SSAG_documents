import numpy as np
import json
import os
import sys
import pandas as pd
from qdrant_client import QdrantClient

from core.config import QDRANT_URL,COLLECTION_NAME, QDRANT_API_KEY



# --- 로컬 파일 설정 (Clustering.py에서 사용될 최종 캐시 파일) ---
ALL_VECTORS_FILE = "all_qdrant_vectors.npy"
ALL_PAYLOADS_FILE = "all_qdrant_payloads.json"
# ----------------------------------------------------


def fetch_and_cache_all_vectors():
    """
    Qdrant에서 모든 청크 벡터와 페이로드를 가져와 로컬에 캐시합니다.
    (Clustering.py에서 사용할 최종 입력 데이터를 준비합니다.)
    """
    
    vectors = None
    payloads = None
    
    # 1. 캐시 파일이 있으면 바로 로드하여 반환
    if os.path.exists(ALL_VECTORS_FILE) and os.path.exists(ALL_PAYLOADS_FILE):
        print(f"[정보] 기존 캐시 파일 로드 중...", file=sys.stderr)
        try:
            vectors = np.load(ALL_VECTORS_FILE)
            with open(ALL_PAYLOADS_FILE, 'r', encoding='utf-8') as f:
                payloads = json.load(f)
            
            if vectors is not None and len(vectors) == len(payloads):
                 print(f"[정보] 캐시 로드 완료. 총 {len(vectors)}개 벡터.", file=sys.stderr)
                 return vectors, payloads
        except Exception as e:
            print(f"[경고] 캐시 파일 로드 실패: {e}. Qdrant에서 새로 가져옵니다.", file=sys.stderr)
            vectors = None
            payloads = None

    # 2. 캐시 파일이 없으면 Qdrant에서 데이터 가져오기 및 저장
    try:
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        if not qdrant_client.collection_exists(collection_name=COLLECTION_NAME):
             print(f"[오류] 컬렉션 '{COLLECTION_NAME}'을(를) 찾을 수 없습니다.", file=sys.stderr)
             return None, None
             
        print(f"[시작] 컬렉션 '{COLLECTION_NAME}'에서 전체 데이터 가져오기 시작.")
        all_vectors = []
        all_payloads = []
        next_offset = None
        
        while True:
            scroll_response, current_offset = qdrant_client.scroll(
                collection_name=COLLECTION_NAME, limit=1000, offset=next_offset,
                with_vectors=True, with_payload=True
            )
            for point in scroll_response:
                all_vectors.append(point.vector)
                payload_data = point.payload.copy()
                payload_data['point_id'] = point.id 
                all_payloads.append(payload_data)
            
            next_offset = current_offset
            if next_offset is None:
                break
        
        if not all_vectors:
            print("[경고] 컬렉션에 저장된 벡터가 없습니다.", file=sys.stderr)
            return None, None

        vectors = np.array(all_vectors, dtype=np.float32)
        payloads = all_payloads
        
        # 캐시 파일 저장
        np.save(ALL_VECTORS_FILE, vectors)
        with open(ALL_PAYLOADS_FILE, 'w', encoding='utf-8') as f:
            json.dump(payloads, f, ensure_ascii=False, indent=2)
            
        print(f"[완료] 총 {len(vectors)}개 청크 벡터 및 페이로드 캐시 저장 완료.")
        return vectors, payloads

    except Exception as e:
        print(f"[오류] Qdrant 데이터 가져오기 실패: {e}", file=sys.stderr)
        return None, None


if __name__ == "__main__":
    
    print(f"--- [Qdrant 데이터 캐시 생성/확인] ---")
    vectors, payloads = fetch_and_cache_all_vectors() 
    
    if vectors is not None:
        print(f"\n[다음 단계 준비 완료] '{ALL_VECTORS_FILE}' 및 '{ALL_PAYLOADS_FILE}'가 준비되었습니다.")