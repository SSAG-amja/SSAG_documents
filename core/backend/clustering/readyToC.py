import numpy as np
import json
import os
import sys
import pandas as pd
from qdrant_client import QdrantClient # 데이터 가져오기 로직 재사용을 위해 필요
import hdbscan # <--- 클러스터링 라이브러리
from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY

# --- 로컬 파일 설정 (현재 실행 디렉토리에 있다고 가정) ---
VECTORS_FILE = "qdrant_vectors.npy"
PAYLOADS_FILE = "qdrant_payloads.json"
# ----------------------------------------------------


# ------------------------------------------------------
# 1. Qdrant 데이터 Fetch 및 Load 함수 (이전 스크립트의 통합)
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
# 2. HDBSCAN 클러스터링 실행 및 분석
# ------------------------------------------------------

def run_clustering_analysis(vectors, payloads):
    """HDBSCAN 클러스터링을 수행하고 결과를 분석합니다."""
    
    print(f"\n[분석] HDBSCAN 클러스터링 시작...", file=sys.stderr)
    
    # --- [중요] HDBSCAN 하이퍼파라미터 설정 ---
    # min_cluster_size: 최소한 이 수 이상의 포인트가 모여야 클러스터로 인정됩니다.
    # 클러스터의 '밀도' 정의에 따라 조정해야 합니다. 너무 크면 클러스터가 적게 나옵니다.
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=3, 
        min_samples=3, 
        metric='euclidean', # 임베딩 벡터에 흔히 사용되는 거리 측정법
    )
    
    # 클러스터링 실행
    clusterer.fit(vectors)
    labels = clusterer.labels_
    
    unique_labels = set(labels)
    # 노이즈(-1)를 제외한 클러스터 개수 계산
    num_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)
    num_noise = list(labels).count(-1)
    
    print(f"[완료] 총 {num_clusters}개 클러스터 생성. 노이즈 포인트: {num_noise}개", file=sys.stderr)

    # 3. 결과 매핑 및 분석 (Payload 사용)
    df = pd.DataFrame(payloads)
    df['cluster_label'] = labels
    
    # 4. 클러스터별 파일 기여도 분석
    # doc_id (파일 경로)에서 파일 이름만 추출하고, 클러스터별로 고유한 파일 목록을 생성
    cluster_summary = df.groupby('cluster_label')['doc_id'].agg(
        lambda x: pd.Series([os.path.basename(p) for p in x.unique()]).tolist()
    ).reset_index()
    
    # 5. 노이즈를 제외한 클러스터만 분석
    meaningful_clusters = cluster_summary[cluster_summary['cluster_label'] != -1]
    
    print("\n" + "="*50)
    print("      클러스터별 파일 기여도 및 크기 요약")
    print("="*50)
    
    for index, row in meaningful_clusters.iterrows():
        cluster_id = row['cluster_label']
        contributing_files = row['doc_id']
        cluster_size = len(df[df['cluster_label'] == cluster_id])
        
        # 클러스터의 대표 텍스트 (첫 번째 청크)
        sample_text = df[df['cluster_label'] == cluster_id]['text_for_embedding'].iloc[0][:100].replace('\n', ' ') + "..."

        print(f"## 🏆 클러스터 {cluster_id} (크기: {cluster_size}개 청크)")
        print(f"  - 대표 내용 (샘플): {sample_text}")
        print(f"  - 기여 파일 ({len(contributing_files)}개): {', '.join(contributing_files)}")
        print("-" * 20)

    print(f"\n[노이즈] 노이즈 포인트 (-1 라벨) 총 {num_noise}개 (클러스터링 되지 않음)")
    print("="*50)


if __name__ == "__main__":
    if fetch_all_vectors_from_qdrant():
        vectors, payloads = load_data_for_clustering()
        
        if vectors is not None and len(vectors) > 0:
            print(f"\n--- [클러스터링 실행] ---")
            run_clustering_analysis(vectors, payloads)
        else:
            print("클러스터링을 위한 데이터가 부족하거나 로드에 실패했습니다.", file=sys.stderr)