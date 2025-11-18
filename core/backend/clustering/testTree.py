import numpy as np
import json
import os
import sys
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
import math
import requests
from qdrant_client import QdrantClient, models
from typing import List, Dict, Any

from core.config import QDRANT_URL, COLLECTION_NAME, QDRANT_API_KEY, SOLAR_API_KEY

SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
SOLAR_MODEL = "solar-pro2"

# --- 파일 경로 설정 (변경 없음) ---
CENTROID_VECTORS_FILE = "centroid_vectors.npy"
CENTROID_PAYLOADS_FILE = "centroid_payloads.json"
OUTPUT_JSON_FILE = "hierarchical_labels.json"

# ------------------------------------------------------------------
# 1. Qdrant 검색 함수 (변경 없음)
# ------------------------------------------------------------------

def real_qdrant_search(query_vector: np.ndarray, k: int = 5) -> List[str]: 
    """
    Centroid 벡터를 쿼리로 사용하여 Qdrant에서 상위 K=5개의 원본 청크 텍스트를 검색합니다.
    """
    try:
        qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        
        search_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector.tolist(),
            limit=k, 
            with_payload=['text_for_embedding'] 
        )
        
        # 원본 텍스트 전체를 반환합니다.
        texts = [result.payload.get('text_for_embedding', '') for result in search_results]
        return texts
        
    except Exception as e:
        print(f"[Qdrant 오류] 검색 실패. API 키나 컬렉션 상태를 확인하세요: {e}", file=sys.stderr)
        return []

# ------------------------------------------------------------------
# 2. LLM 호출 함수 (키워드 추출 및 최종 라벨 생성) (변경 없음)
# ------------------------------------------------------------------

KEYWORD_PROMPT_TEMPLATE = """
Analyze the following text chunk. Your task is to provide 3 to 5 comma-separated keywords or a single, concise phrase (maximum 5 words) that summarize the core topic discussed in this chunk. Do not include any introductory phrases or explanations, just the keywords/phrase.

[TEXT CHUNK]
---
{chunk_text}
---
Keywords/Phrase:
"""

FINAL_LABEL_PROMPT_TEMPLATE = """
Analyze the following list of keywords and phrases, which summarize the central themes of a single data cluster. Your task is to provide a single, concise category label (maximum 3 words) that accurately represents ALL the themes. Do not include any introductory phrases or explanations, just the label.

[KEYWORD LIST]
---
{keyword_list}
---
Label:
"""

def _call_solar_llm(prompt: str, node_id: Any, max_tokens: int, purpose: str) -> str:
    """LLM 호출을 위한 내부 범용 함수"""
    headers = {
        "Authorization": f"Bearer {SOLAR_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": SOLAR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens
    }

    try:
        response = requests.post(
            SOLAR_LLM_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=120  
        )
        response.raise_for_status()

        response_json = response.json()
        
        if response_json['choices'] and response_json['choices'][0]['message']:
            content = response_json['choices'][0]['message']['content']
            return content.split('\n')[0].replace('"', '').replace('Keywords/Phrase:', '').replace('Label:', '').strip()
        else:
            return f"{purpose.upper()}_PARSE_FAIL_Node_{node_id}"

    except requests.exceptions.RequestException as e:
        print(f"[LLM HTTP 오류 - {purpose.upper()}] 노드 {node_id} 요청 실패: {e}", file=sys.stderr)
        return f"{purpose.upper()}_ERROR_Node_{node_id}"
    except Exception as e:
        print(f"[LLM 오류 - {purpose.upper()}] 노드 {node_id} 알 수 없는 오류: {e}", file=sys.stderr)
        return f"{purpose.upper()}_UNKNOWN_ERROR_Node_{node_id}"

def call_solar_llm_for_keywords(chunk_text: str, node_id: Any, chunk_index: int) -> str:
    """단일 텍스트 청크로부터 키워드를 추출하는 LLM 호출 (5회 중 1회)"""
    formatted_prompt = KEYWORD_PROMPT_TEMPLATE.format(chunk_text=chunk_text)
    return _call_solar_llm(formatted_prompt, f"{node_id}-{chunk_index}", max_tokens=30, purpose="KEYWORD")

def call_solar_llm_for_labeling(keyword_list: List[str], node_id: Any) -> str:
    """추출된 키워드 목록을 기반으로 최종 라벨을 생성하는 LLM 호출 (1회)"""
    combined_keywords = ", ".join(keyword_list)
    formatted_prompt = FINAL_LABEL_PROMPT_TEMPLATE.format(keyword_list=combined_keywords)
    return _call_solar_llm(formatted_prompt, node_id, max_tokens=20, purpose="LABEL")

# ------------------------------------------------------------------
# 3. 메인 로직: 계층 구조 순회 및 라벨링
# ------------------------------------------------------------------

def get_node_centroid_map(df: pd.DataFrame, vectors: np.ndarray) -> Dict[int, np.ndarray]:
    """Centroid 벡터 배열을 파일 인덱스(0 to N-1)와 매핑하는 딕셔너리를 반환합니다."""
    return {i: vectors[i] for i in df.index}

def generate_hierarchical_labels():
    
    # 1. 데이터 로드
    print("[진단] 1. 파일 존재 여부 확인 시작...", file=sys.stderr) # <-- 진단 메시지 1
    
    # 현재 실행 디렉토리를 기준으로 절대 경로를 확인합니다.
    current_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
    vector_path = os.path.join(current_dir, CENTROID_VECTORS_FILE)
    payload_path = os.path.join(current_dir, CENTROID_PAYLOADS_FILE)

    if not os.path.exists(vector_path) or not os.path.exists(payload_path):
        print("------------------------------------------------------------------", file=sys.stderr)
        print(f"[오류] 필수 파일이 없습니다. 경로 확인:", file=sys.stderr)
        print(f"  > 벡터 파일 기대 경로: {vector_path}", file=sys.stderr)
        print(f"  > 페이로드 파일 기대 경로: {payload_path}", file=sys.stderr)
        print("------------------------------------------------------------------", file=sys.stderr)
        return
    
    print("[진단] 2. 파일 존재 확인 완료. 로드 시도...", file=sys.stderr) # <-- 진단 메시지 2

    try:
        centroid_vectors = np.load(vector_path)
        print("[진단] 3. 벡터 파일 로드 성공.", file=sys.stderr) # <-- 진단 메시지 3
        
        with open(payload_path, 'r', encoding='utf-8') as f:
            centroid_payloads = json.load(f)
        print("[진단] 4. 페이로드 파일 로드 성공.", file=sys.stderr) # <-- 진단 메시지 4
            
        N_files = len(centroid_vectors)
        if N_files < 2:
            print("[경고] 파일이 2개 미만이어서 클러스터링을 할 수 없습니다.", file=sys.stderr)
            return
        
    except Exception as e:
        print(f"------------------------------------------------------------------", file=sys.stderr)
        print(f"[오류] 데이터 로드 중 실패: {e}", file=sys.stderr)
        print(f"  > 파일 내용이 손상되었거나 형식이 잘못되었을 수 있습니다. 확인해 주세요.", file=sys.stderr)
        print(f"------------------------------------------------------------------", file=sys.stderr)
        return

    # 2. Agglomerative Clustering 준비 (변경 없음)
    df = pd.DataFrame(centroid_payloads)
    df['vector'] = list(centroid_vectors) 

    # 3. Agglomerative Clustering 및 링크 행렬(Z) 생성 (변경 없음)
    Z = linkage(centroid_vectors, method='average', metric='cosine')
    
    # 4. 동적 커팅 (K개 최종 클러스터 확정) (변경 없음)
    K_target = max(2, math.ceil(N_files * 0.3))
    print(f"[설정] 동적 커팅 목표 클러스터 개수 (K): {K_target}", file=sys.stderr)
    
    final_cluster_labels = fcluster(Z, t=K_target, criterion='maxclust')
    df['final_label'] = final_cluster_labels
    
    # --- 5. 계층 구조 순회 및 JSON 출력 준비 ---

    output_relations = []
    node_labels = {} 
    
    # 5-A. 최종 K개 클러스터 라벨링 (Leaf Nodes 바로 위의 부모 노드)
    print(f"[라벨링] 최종 {K_target}개 클러스터 라벨링 시작...", file=sys.stderr)
    
    for cluster_id in np.unique(final_cluster_labels):
        files_in_cluster = df[df['final_label'] == cluster_id]
        
        # 1. 클러스터 Centroid 계산 
        vectors_in_cluster = files_in_cluster['vector'].values
        cluster_centroid_vector = np.mean(np.stack(vectors_in_cluster), axis=0)
        
        # 2. Qdrant 검색 (대표 텍스트 5개 검색)
        representative_texts = real_qdrant_search(cluster_centroid_vector, k=5) 
        
        # 3. LLM 6회 호출 시작
        if not representative_texts:
            llm_label = f"Unknown_Empty_Topic_{cluster_id}"
        else:
            keyword_list = []
            print(f"    -> 노드 {cluster_id}: 텍스트 5개에서 키워드 추출 중...", file=sys.stderr)
            for i, text in enumerate(representative_texts):
                # 키워드 추출 (LLM 호출 1~5회)
                keyword = call_solar_llm_for_keywords(text, cluster_id, i)
                keyword_list.append(keyword)
            
            # 최종 라벨 생성 (LLM 호출 6회째)
            llm_label = call_solar_llm_for_labeling(keyword_list, cluster_id)

        # 라벨 저장
        node_labels[f'Final_{cluster_id}'] = llm_label

        # 4. 파일 매핑: (Category, doc_id) 쌍 생성
        # 파일은 이 최종 클러스터 라벨에만 연결됩니다.
        for index, row in files_in_cluster.iterrows():
            doc_id_basename = os.path.basename(row['doc_id'])
            output_relations.append((llm_label, doc_id_basename))

    # 5-B. 상위 계층 구조 순회 및 라벨링 (K개 클러스터 위쪽 트리의 루트까지)
    
    print(f"[라벨링] 상위 부모 노드 라벨링 시작...", file=sys.stderr)
    
    # Centroid 계산 및 검색을 위한 맵 준비
    node_vector_map = get_node_centroid_map(df, centroid_vectors)
    
    for i in range(len(Z)):
        node_index = N_files + i 
        left_child_id = int(Z[i, 0])
        right_child_id = int(Z[i, 1])
        
        # 1. 자식 Centroid 벡터 가져오기
        V_L = node_vector_map.get(left_child_id)
        V_R = node_vector_map.get(right_child_id)
        
        if V_L is None or V_R is None:
            print(f"[경고] 노드 {node_index}에서 자식 Centroid를 찾을 수 없습니다. 건너뜀.", file=sys.stderr)
            continue
            
        # 2. 새로운 부모 노드 Centroid 계산
        parent_centroid_vector = np.mean([V_L, V_R], axis=0)
        
        # 3. 새로운 Centroid를 맵에 저장 (다음 병합 단계에서 재사용)
        node_vector_map[node_index] = parent_centroid_vector 
        
        # 4. Qdrant 검색 (대표 텍스트 5개 검색)
        representative_texts = real_qdrant_search(parent_centroid_vector, k=5) 
        
        # 5. LLM 6회 호출 시작
        if not representative_texts:
            parent_label = f"Unknown_Empty_Topic_{node_index}"
        else:
            keyword_list = []
            print(f"    -> 노드 {node_index}: 텍스트 5개에서 키워드 추출 중...", file=sys.stderr)
            for i, text in enumerate(representative_texts):
                # 키워드 추출 (LLM 호출 1~5회)
                keyword = call_solar_llm_for_keywords(text, node_index, i)
                keyword_list.append(keyword)
            
            # 최종 라벨 생성 (LLM 호출 6회째)
            parent_label = call_solar_llm_for_labeling(keyword_list, node_index)
             
        # 6. 라벨 저장
        node_labels[str(node_index)] = parent_label
        
        # 7. JSON 튜플 생성: (Parent_Category, Child_Category or doc_id)
        
        # 좌측 자식 라벨 결정
        if left_child_id < N_files:
            # 자식 노드가 파일인 경우, 자식 파일 대신 자식 파일이 속한 최종 클러스터 라벨을 연결
            child_cluster_label = df[df.index == left_child_id]['final_label'].iloc[0]
            child_label = node_labels.get(f"Final_{child_cluster_label}")
        else:
            child_label = node_labels.get(str(left_child_id), f"Cluster_{left_child_id}")
            
        # 자식 라벨이 유효한 경우에만 추가
        if child_label:
             output_relations.append((parent_label, child_label))
            
        # 우측 자식 라벨 결정
        if right_child_id < N_files:
            # 자식 노드가 파일인 경우, 자식 파일 대신 자식 파일이 속한 최종 클러스터 라벨을 연결
            child_cluster_label = df[df.index == right_child_id]['final_label'].iloc[0]
            child_label = node_labels.get(f"Final_{child_cluster_label}")
        else:
            child_label = node_labels.get(str(right_child_id), f"Cluster_{right_child_id}")
            
        # 자식 라벨이 유효한 경우에만 추가
        if child_label:
             output_relations.append((parent_label, child_label))


    # 6. 최종 JSON 저장
    with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_relations, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] 계층적 라벨 구조 JSON 파일 저장 완료.")
    print(f"  > 파일: {OUTPUT_JSON_FILE}")


if __name__ == "__main__":
    generate_hierarchical_labels()