import numpy as np
import json
import os
import sys
import pandas as pd
from qdrant_client import QdrantClient

from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY

# --- 로컬 파일 설정 (현재 코드 위치에 저장) ---
# 모든 청크 데이터 캐시 (임시로 사용)
ALL_VECTORS_FILE = "all_qdrant_vectors.npy"
ALL_PAYLOADS_FILE = "all_qdrant_payloads.json"

# 최종 대표 벡터 결과 파일
CENTROID_VECTORS_FILE = "centroid_vectors.npy"
CENTROID_PAYLOADS_FILE = "centroid_payloads.json"

def fetch_and_calculate_centroids():
    """
    Qdrant에서 모든 데이터를 가져와 파일별 Centroid를 계산하고 저장합니다.
    """
    
    # 1. Qdrant 데이터 가져오기 (이전 코드 재사용)
    
    # 캐시 파일이 있으면 바로 로드하여 계산에 사용합니다.
    if os.path.exists(ALL_VECTORS_FILE) and os.path.exists(ALL_PAYLOADS_FILE):
        print(f"[정보] 기존 캐시 파일 로드 중...", file=sys.stderr)
        vectors = np.load(ALL_VECTORS_FILE)
        with open(ALL_PAYLOADS_FILE, 'r', encoding='utf-8') as f:
            payloads = json.load(f)
    else:
        # 캐시 파일이 없으면 Qdrant에서 가져와 임시 저장
        try:
            qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
            
            # ... (컬렉션 존재 확인 로직 생략) ...
            
            print(f"[시작] 컬렉션에서 전체 데이터 가져오기 시작...", file=sys.stderr)
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
                return False

            vectors = np.array(all_vectors, dtype=np.float32)
            payloads = all_payloads
            
            # (선택 사항) 다음 실행을 위해 임시 전체 벡터 캐시를 저장합니다.
            np.save(ALL_VECTORS_FILE, vectors)
            with open(ALL_PAYLOADS_FILE, 'w', encoding='utf-8') as f:
                json.dump(payloads, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"[오류] Qdrant 데이터 가져오기 실패: {e}", file=sys.stderr)
            return False

    # 2. 파일별 Centroid 계산 및 대표 페이로드 추출
    
    df = pd.DataFrame(payloads)
    
    # 각 point_id와 벡터를 매핑하는 딕셔너리 생성
    # [수정]: p.id 오류 수정 -> map_id: v 로 변경
    vector_map = {map_id: v for map_id, v in zip(df['point_id'], vectors)}
    
    # DataFrame에 실제 벡터 추가
    df['vector'] = df['point_id'].map(vector_map)
    
    if df['vector'].isnull().any():
        print("[오류] 벡터 매핑 실패: 데이터 불일치.", file=sys.stderr)
        return False
        
    print(f"\n[단계 1] 파일별 Centroid 벡터 계산 시작...", file=sys.stderr)

    # Centroid 계산 (Centroid: 해당 그룹 벡터들의 평균)
    centroid_series = df.groupby('doc_id')['vector'].apply(
        lambda x: np.mean(list(x), axis=0) # 벡터 리스트의 평균을 구함
    )
    
    # 3. 최종 결과 구조화
    centroid_vectors_list = []
    centroid_payloads_list = []

    for doc_id, centroid_vector in centroid_series.items():
        # Centroid 벡터 리스트에 추가
        centroid_vectors_list.append(centroid_vector)
        
        # 대표 페이로드 추출: 해당 파일의 첫 번째 청크 페이로드를 대표로 사용
        # (Centroid 벡터 자체는 원본 텍스트가 없으므로, 파일의 첫 청크 텍스트를 대표로 삼음)
        # .iloc[0]을 사용하여 해당 doc_id의 첫 번째 행(청크)을 대표로 선택
        representative_payload = df[df['doc_id'] == doc_id].iloc[0].to_dict()
        
        # Centroid 계산 결과에는 불필요한 청크 정보 제거
        del representative_payload['vector']
        
        # 새로운 Centroid를 명시
        representative_payload['is_centroid'] = True
        
        centroid_payloads_list.append(representative_payload)

    # 4. 최종 캐시 파일 저장
    
    centroid_vectors_array = np.stack(centroid_vectors_list)

    np.save(CENTROID_VECTORS_FILE, centroid_vectors_array)
    with open(CENTROID_PAYLOADS_FILE, 'w', encoding='utf-8') as f:
        json.dump(centroid_payloads_list, f, ensure_ascii=False, indent=2)

    print(f"[완료] 총 {len(centroid_vectors_list)}개 파일 Centroid 저장 완료.")
    print(f"  > 대표 벡터 파일: {CENTROID_VECTORS_FILE}")
    print(f"  > 대표 페이로드 파일: {CENTROID_PAYLOADS_FILE}")
    
    # 5. (선택 사항) 임시 전체 벡터 캐시 삭제 - 선택적으로 주석 처리
    # os.remove(ALL_VECTORS_FILE)
    # os.remove(ALL_PAYLOADS_FILE)

    return True


if __name__ == "__main__":
    if fetch_and_calculate_centroids():
        # 이제 centroid_vectors.npy와 centroid_payloads.json 파일을 사용하여
        # 파일 기반 클러스터링을 진행할 수 있습니다.
        pass