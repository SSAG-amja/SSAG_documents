import numpy as np
import json
import os
import sys
import requests
import re
from qdrant_client import QdrantClient
from typing import List, Dict, Any, Set, Tuple

from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY, SOLAR_API_KEY


SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
SOLAR_MODEL = "solar-pro2"

# --- 입력/출력 파일 경로 설정 ---
FINAL_MAPPING_FILE = "final_file_cluster_mapping.json"
CENTROID_VECTORS_FILE = "hdbscan_cluster_centroids.npy"
OUTPUT_JSON_FILE = "hdbscan_cluster_labels.json" 

# ------------------------------------------------------------------
# 1. Qdrant 검색 함수
# ------------------------------------------------------------------

def real_qdrant_search(query_vector: np.ndarray, k: int = 5) -> List[str]: 
    """Centroid 벡터를 쿼리로 사용하여 Qdrant에서 상위 K=5개의 원본 청크의 summary를 검색합니다."""
    try:
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        
        # Qdrant 검색 (Centroid 벡터와 가장 가까운 청크를 찾음)
        search_result = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector.tolist(),
            limit=k,
            with_payload=['summary'] # summary 페이로드만 가져옵니다.
        )
        
        # 검색된 summary 텍스트만 추출하여 리스트로 반환
        summaries = [hit.payload.get('summary', '') for hit in search_result if 'summary' in hit.payload]
        return summaries
    
    except Exception as e:
        print(f"[오류] Qdrant 검색 실패: {e}", file=sys.stderr)
        return []

# ------------------------------------------------------------------
# 2. Solar LLM 호출 함수
# ------------------------------------------------------------------

def call_solar_llm_for_labeling(summaries: List[str], existing_labels: Set[str], cluster_id: int) -> str:
    """
    제공된 summary들을 기반으로 Solar LLM을 호출하여 클러스터에 대한 카테고리 이름을 생성합니다.
    """
    
    # 1. 프롬프트 구성
    summaries_text = "\n".join([f"- {s}" for s in summaries])
    existing_labels_text = ", ".join(existing_labels)
    
    prompt = f"""
    규칙:
    1. 반드시 한 단어 또는 두 단어 정도의 짧은 카테고리 이름만 출력한다.
    2. 출력은 오직 카테고리 이름 한 줄만 포함해야 한다.
    3. 문장, 설명, 이유, 예시, 접두사, 접미사, 따옴표, 코멘트 금지.
    4. 기존 카테고리와 동일한 이름 금지.
    5. 한국어 명사 형태로 출력.

    아래는 하나의 클러스터에 속한 문서들의 summary 목록이다.
    이 summary들의 공통 주제를 가장 잘 대표하는 단일 카테고리 이름만 생성하라.

    [요약 목록]
    {summaries_text}

    기존 카테고리: {existing_labels_text}

    출력형식(예시):
    컴퓨터 구조

    """
    
    # 2. API 호출
    headers = {
        "Authorization": f"Bearer {SOLAR_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": SOLAR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 15, # 카테고리 이름이므로 짧게 제한
        "stop" : "\n"
    }
    
    try:
        response = requests.post(SOLAR_LLM_ENDPOINT, headers=headers, json=data)
        response.raise_for_status() # HTTP 오류 발생 시 예외 발생
        
        result = response.json()
        llm_label_raw = result['choices'][0]['message']['content'].strip()
        
        # LLM의 출력이 따옴표 등으로 감싸져 있을 수 있으므로 제거
        llm_label = llm_label_raw.strip("'\"") 
        
        # 3. 안전 및 중복 방지 로직
        # LLM이 지시를 어기고 중복된 이름을 생성했을 경우 임시로 보완
        if llm_label in existing_labels:
             llm_label = f"{llm_label}_{cluster_id}" # 임시로 클러스터 ID를 붙여 고유하게 만듦
             print(f"[경고] 중복 라벨 발생. 임시 보정: {llm_label}", file=sys.stderr)
             
        return llm_label
        
    except requests.exceptions.RequestException as e:
        print(f"[오류] Solar LLM API 호출 실패: {e}", file=sys.stderr)
        return f"LLM_ERROR_{cluster_id}"

# ------------------------------------------------------------------
# 3. 라벨링 메인 프로세스
# ------------------------------------------------------------------

def run_labeling_process() -> bool:
    
    try:
        # 1. 입력 파일 로드
        print(f"[로딩] Centroid 벡터 로드: {CENTROID_VECTORS_FILE}")
        centroid_vectors = np.load(CENTROID_VECTORS_FILE)
        
        print(f"[로딩] 파일-클러스터 매핑 로드: {FINAL_MAPPING_FILE}")
        with open(FINAL_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
            mapping = mapping_data['mapping']
            
            # 클러스터 ID -> Centroid 벡터 인덱스 매핑 로드
            cluster_id_to_index = {int(k): v for k, v in mapping_data.get('cluster_id_to_index', {}).items()}
            assigned_cluster_ids = mapping_data.get('assigned_cluster_ids', [])

        cluster_labels_map: Dict[int, str] = {} # {cluster_id: 'LLM_Label'}
        existing_labels_set: Set[str] = set() # 중복 체크용
        
        # 2. 각 클러스터별로 라벨링 수행
        print(f"\n[LLM 라벨링 시작] 총 {len(assigned_cluster_ids)}개 클러스터 대상.")
        
        for cluster_id in assigned_cluster_ids:
            
            # 해당 클러스터의 Centroid 벡터 가져오기
            index = cluster_id_to_index.get(cluster_id)
            if index is None or index >= len(centroid_vectors):
                print(f"[경고] 클러스터 ID {cluster_id}에 대한 Centroid 벡터를 찾을 수 없습니다.", file=sys.stderr)
                continue
                
            centroid_vector = centroid_vectors[index]
            
            # Centroid 벡터로 Qdrant 검색 (대표 summary 획득)
            representative_summaries = real_qdrant_search(centroid_vector)
            unique_summaries = list(set(representative_summaries))
            
            # LLM 호출
            if not unique_summaries:
                llm_label = f"빈_주제_{cluster_id}"
            else:
                # print(f"    -> 클러스터 {cluster_id}: {len(unique_summaries)}개 Summary로 카테고리 선정 중...", file=sys.stderr)
                llm_label = call_solar_llm_for_labeling(unique_summaries, existing_labels_set, cluster_id)
                 
            # 라벨 저장 및 중복 Set에 추가
            cluster_labels_map[cluster_id] = llm_label
            existing_labels_set.add(llm_label)
            print(f"  -> 클러스터 {cluster_id}: '{llm_label}' 할당 완료.")


        # 3. 최종 JSON 구조 생성 및 저장
        
        output_relations = []
        
        # 파일-클러스터 매핑을 순회하며 최종 카테고리로 변환
        for item in mapping:
            doc_id = item['doc_id']
            cluster_id = item['cluster_id']
            
            if cluster_id != -1: 
                llm_label = cluster_labels_map.get(cluster_id, f"ERROR_카테고리_{cluster_id}")
                output_relations.append([llm_label, doc_id])

        # 노이즈 파일 목록 추가 (별도 주제로 분류)
        noise_files = mapping_data.get("noise_files", [])
        if noise_files:
            noise_label = "미분류 주제"
            for doc_id in noise_files:
                output_relations.append([noise_label, doc_id])
                
        # 최종 JSON 파일 저장 (ClusterCategory.py의 입력)
        with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_relations, f, ensure_ascii=False, indent=2)
            
        print(f"\n[저장 완료] 최종 파일-카테고리 매핑 저장: {OUTPUT_JSON_FILE}")
        return True

    except Exception as e:
        print(f"[치명적 오류] 라벨링 프로세스 중 예외 발생: {e}", file=sys.stderr)
        return False
        
# ------------------------------------------------------------------
# 4. 정리 함수 (새로 추가)
# ------------------------------------------------------------------

def cleanup_intermediate_files():
    """Centroid 벡터 및 파일-클러스터 매핑 파일을 삭제합니다."""
    
    if os.path.exists(CENTROID_VECTORS_FILE):
        os.remove(CENTROID_VECTORS_FILE)
        print(f"\n[삭제 완료] Centroid 벡터 파일 삭제: {CENTROID_VECTORS_FILE}")
    if os.path.exists(FINAL_MAPPING_FILE):
        os.remove(FINAL_MAPPING_FILE)
        print(f"[삭제 완료] 파일-클러스터 매핑 파일 삭제: {FINAL_MAPPING_FILE}")
        
# ------------------------------------------------------------------
# 5. 메인 실행 로직 수정
# ------------------------------------------------------------------

if __name__ == "__main__":
    
    print(f"--- [클러스터 라벨링 시작] ---")
    
    # 입력 파일 존재 여부 확인
    if os.path.exists(CENTROID_VECTORS_FILE) and os.path.exists(FINAL_MAPPING_FILE):
        if run_labeling_process():
            print("\n[전체 완료] 클러스터 라벨링 및 파일 매핑 JSON 저장이 완료되었습니다.")
            
            # --- [요청하신 파일 삭제] ---
            cleanup_intermediate_files() 
            
            print("\n[다음 단계] ClusterCategory.py 실행 준비 완료.")
        else:
            print("[오류] 라벨링 프로세스 실패.", file=sys.stderr)
    else:
        print(f"[오류] 입력 파일 부족. Clustering.py를 먼저 실행해야 합니다.", file=sys.stderr)
        print(f"  필요한 파일: {CENTROID_VECTORS_FILE}, {FINAL_MAPPING_FILE}", file=sys.stderr)