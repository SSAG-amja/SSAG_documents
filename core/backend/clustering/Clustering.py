import numpy as np
import json
import os
import sys
import pandas as pd
from qdrant_client import QdrantClient
import hdbscan
from collections import Counter
from typing import Dict, List, Any

from core.config import COLLECTION_NAME, QDRANT_API_KEY, QDRANT_URL


# --- 로컬 파일 설정 (vectorPull.py에서 생성됨) ---
VECTORS_FILE = "all_qdrant_vectors.npy"
PAYLOADS_FILE = "all_qdrant_payloads.json"

# --- 출력 파일 설정 ---
FINAL_MAPPING_FILE = "final_file_cluster_mapping.json"
CENTROID_VECTORS_FILE = "hdbscan_cluster_centroids.npy"

# ------------------------------------------------------
# 1. Qdrant 데이터 Fetch 및 Load 함수
# ------------------------------------------------------

def fetch_all_vectors_from_qdrant():
    """Qdrant에서 데이터를 가져와 로컬에 캐시합니다."""
    
    if os.path.exists(VECTORS_FILE) and os.path.exists(PAYLOADS_FILE):
        print(f"[정보] 로컬 캐시 파일이 이미 존재합니다. 분석을 바로 시작합니다.")
        return True
    
    try:
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        if not qdrant_client.collection_exists(collection_name=COLLECTION_NAME):
             print(f"[오류] 컬렉션 '{COLLECTION_NAME}'을(를) 찾을 수 없습니다.", file=sys.stderr)
             return False
        
        print(f"[시작] 컬렉션 '{COLLECTION_NAME}'에서 데이터 가져오기 시작. (최초 다운로드)")
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

        vectors_array = np.array(all_vectors, dtype=np.float32)
        
        np.save(VECTORS_FILE, vectors_array)
        with open(PAYLOADS_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_payloads, f, ensure_ascii=False, indent=2)
            
        print(f"[완료] 총 {len(vectors_array)}개 벡터와 페이로드 저장 완료. (클러스터링 준비 완료)")
        return True

    except Exception as e:
        print(f"[오류] Qdrant 데이터 가져오기 실패: {e}", file=sys.stderr)
        return False

def load_data_for_clustering():
    """로컬에 저장된 벡터와 페이로드를 메모리로 로드합니다."""
    
    if not os.path.exists(VECTORS_FILE) or not os.path.exists(PAYLOADS_FILE):
        return None, None
        
    vectors = np.load(VECTORS_FILE)
    with open(PAYLOADS_FILE, 'r', encoding='utf-8') as f:
        payloads = json.load(f)
        
    return vectors, payloads


# ------------------------------------------------------
# 2. HDBSCAN 실행 및 파일 투표 시스템
# ------------------------------------------------------

def run_file_centric_hdbscan(vectors: np.ndarray, payloads: List[Dict[str, Any]]):
    """
    HDBSCAN을 청크 벡터에 대해 실행하고, 파일 투표를 통해 파일의 클러스터를 확정하고 결과를 저장합니다.
    """
    df = pd.DataFrame(payloads)
    
    # 1. 벡터 정규화
    vectors_normalized = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    
    # 2. HDBSCAN 하이퍼파라미터 설정 (이전 실행 결과를 바탕으로 수동 설정)
    MIN_CLUSTER_SIZE = 2  # <-- 클러스터 생성을 위해 기준 완화
    MIN_SAMPLES = 1       # <-- 밀도 기준 최소화
    
    print(f"\n[설정] HDBSCAN 시작. (min_cluster_size={MIN_CLUSTER_SIZE}, min_samples={MIN_SAMPLES})", file=sys.stderr)
    
    # 3. HDBSCAN 클러스터링 실행
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE, 
        min_samples=MIN_SAMPLES, 
        metric='euclidean',
    )
    
    clusterer.fit(vectors_normalized)
    df['cluster_label'] = clusterer.labels_
    
    # 4. 파일 투표 시스템을 통한 클러스터 소속 확정
    final_file_cluster = {} # {doc_id: cluster_id}
    
    for doc_id, group in df.groupby('doc_id'):
        valid_labels = group[group['cluster_label'] != -1]['cluster_label']
        
        if valid_labels.empty:
            final_file_cluster[doc_id] = -1 
            continue
            
        vote_counts = Counter(valid_labels)
        best_label = vote_counts.most_common(1)[0][0]
        final_file_cluster[doc_id] = best_label

    # 5. 클러스터 정제 및 Centroid 계산
    
    assigned_cluster_ids = sorted(list(set(final_file_cluster.values()) - {-1}))
    
    final_mapping_data = [] # 다음 단계로 전달할 파일-클러스터 매핑
    centroid_vectors_list = []
    cluster_id_to_index = {} # {cluster_id: index for numpy array}
    
    for index, cluster_id in enumerate(assigned_cluster_ids):
        
        # Centroid 계산 (해당 클러스터에 속한 모든 청크 벡터의 평균)
        cluster_chunks_indices = df[df['cluster_label'] == cluster_id].index
        
        # 정규화된 벡터 대신 원본 벡터를 사용해 Centroid를 계산하는 것이 더 일반적입니다. (Qdrant 검색 시 사용)
        cluster_vectors = vectors[cluster_chunks_indices]
        centroid = np.mean(cluster_vectors, axis=0)
        
        centroid_vectors_list.append(centroid)
        cluster_id_to_index[cluster_id] = index
        
        # 해당 클러스터에 할당된 파일 목록을 final_mapping_data에 추가
        files_in_cluster = [
            {'doc_id': doc_id, 'cluster_id': cluster_id} 
            for doc_id, c_id in final_file_cluster.items() if c_id == cluster_id
        ]
        final_mapping_data.extend(files_in_cluster)


    # 6. 최종 결과 저장
    
    # (1) 클러스터 Centroid 벡터 저장
    centroid_vectors_array = np.stack(centroid_vectors_list)
    np.save(CENTROID_VECTORS_FILE, centroid_vectors_array)
    print(f"\n[저장 완료] Centroid 벡터 ({len(centroid_vectors_array)}개) 저장: {CENTROID_VECTORS_FILE}")
    
    # (2) 파일-클러스터 매핑 및 메타데이터 저장
    with open(FINAL_MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            "mapping": final_mapping_data,
            "assigned_cluster_ids": assigned_cluster_ids,
            "cluster_id_to_index": cluster_id_to_index, # 라벨링 단계에서 Centroid 찾기 위함
            "noise_files": [doc_id for doc_id, c_id in final_file_cluster.items() if c_id == -1]
        }, f, ensure_ascii=False, indent=2)
    print(f"[저장 완료] 최종 파일-클러스터 매핑 저장: {FINAL_MAPPING_FILE}")
    
    return True

# ------------------------------------------------------
# 3. 캐시 파일 삭제 함수 (새로 추가)
# ------------------------------------------------------

def cleanup_cache():
    """HDBSCAN 완료 후 임시 캐시 파일을 삭제합니다."""
    
    if os.path.exists(VECTORS_FILE):
        os.remove(VECTORS_FILE)
        print(f"\n[삭제 완료] 캐시 벡터 파일 삭제: {VECTORS_FILE}")
    if os.path.exists(PAYLOADS_FILE):
        os.remove(PAYLOADS_FILE)
        print(f"[삭제 완료] 캐시 페이로드 파일 삭제: {PAYLOADS_FILE}")

if __name__ == "__main__":
    
    # NOTE: vectorPull.py가 먼저 실행되어 캐시 파일을 생성했다고 가정합니다.
    # Clustering.py의 fetch 함수는 파일이 있으면 로드합니다.
    if fetch_all_vectors_from_qdrant():
        vectors, payloads = load_data_for_clustering()
        
        if vectors is not None and len(vectors) > 0:
            print(f"\n--- [HDBSCAN 파일 중심 클러스터링 실행] ---")
            run_file_centric_hdbscan(vectors, payloads)
            
            # --- [요청하신 캐시 파일 삭제] ---
            cleanup_cache()
            
        else:
            print("클러스터링을 위한 데이터가 부족하거나 로드에 실패했습니다.", file=sys.stderr)