import json
import os
import sys
import requests
import re

from core.config import SOLAR_API_KEY

# --- Qdrant 및 Solar LLM 설정 ---
# NOTE: Qdrant는 이 단계에서 사용되지 않지만, API 키 설정을 유지합니다. 
SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
SOLAR_MODEL = "solar-pro2"

# --- 입력/출력 파일 경로 설정 ---
INPUT_MAPPING_FILE = "hdbscan_cluster_labels.json" # hdbscan_labeling.py의 출력 파일
OUTPUT_HIERARCHY_FILE = "final_hierarchy_relations.json" # 최종 계층 구조 튜플 JSON

# ------------------------------------------------------------------
# 1. LLM 호출 함수 및 프롬프트 정의
# ------------------------------------------------------------------

HIERARCHY_PROMPT_TEMPLATE = """
규칙:
- 카테고리 리스트에 있는 카테고리도 상위카테고리와 함께 출력에 포함할 것
- 최상위 카테고리는 전체 출력에서 무조건 한개이며, 상위카테고리를 null로 표시
- 카테고리를 비교하다가 필요하면 새로운 상위 카테고리를 생성해도 됨
- 실존 단어 또는 개념을 상위 카테고리 이름으로 만들 것
- 다른 설명이나 텍스트는 포함하지 말고 출력형식을 지켜야함
- 출력 형식은 다음과 같아야 함:  
  (null, 상위카테고리),  
  (상위카테고리, 하위카테고리),  
  (상위카테고리, 하위카테고리) ...

아래 카테고리 리스트를 의미적으로 분석하여
1) 서로 가장 가까운 것끼리 먼저 묶고
2) 의미상 멀다면 새로운 상위 카테고리를 생성하고
3) bottom-up 방식으로 트리 구조를 만들고
4) 트리의 모든 상-하 관계를 (상위카테고리, 하위카테고리) 형식으로 출력해줘.

카테고리 리스트:
—
{category_list}
—
튜플 목록:  
"""

def _call_solar_llm(prompt: str, max_tokens: int) -> str:
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
            return response_json['choices'][0]['message']['content'].strip()
        else:
            return "LLM_RESPONSE_FAILURE"

    except requests.exceptions.RequestException as e:
        print(f"[LLM HTTP 오류] 요청 실패: {e}", file=sys.stderr)
        return "LLM_HTTP_ERROR"
    except Exception as e:
        print(f"[LLM 오류] 알 수 없는 오류: {e}", file=sys.stderr)
        return "LLM_UNKNOWN_ERROR"

# ------------------------------------------------------------------
# 2. 메인 로직: 계층 구조 생성 및 파싱
# ------------------------------------------------------------------

def generate_hierarchy_relations():
    
    # 1. 데이터 로드 및 고유 카테고리 추출
    if not os.path.exists(INPUT_MAPPING_FILE):
        print(f"[오류] 입력 파일이 없습니다. {os.path.basename(INPUT_MAPPING_FILE)}을(를) 먼저 생성하세요.", file=sys.stderr)
        return
    
    with open(INPUT_MAPPING_FILE, 'r', encoding='utf-8') as f:
        mapping_data = json.load(f)
        
    unique_categories = set()
    for category, file_or_doc in mapping_data:
        # 파일 이름과 '미분류 주제' 카테고리는 계층 정의 대상에서 제외
        if category != "미분류 주제" and category not in [item[1] for item in mapping_data]:
             unique_categories.add(category)
             
    category_list_str = "\n".join(sorted(list(unique_categories)))
    
    if not unique_categories:
        print("[경고] 유효한 카테고리가 없어 계층 구조 생성을 건너뜁니다.", file=sys.stderr)
        return
        
    print(f"\n[시작] {len(unique_categories)}개 카테고리로 계층 구조 생성 시작.", file=sys.stderr)

    # 2. LLM 호출 프롬프트 생성
    formatted_prompt = HIERARCHY_PROMPT_TEMPLATE.format(
        category_list=category_list_str,
        total_count=len(unique_categories)
    )
    
    # 3. LLM 호출
    llm_output_raw = _call_solar_llm(formatted_prompt, max_tokens=200)
    
    if "ERROR" in llm_output_raw:
        print(f"[오류] LLM 호출 실패: {llm_output_raw}", file=sys.stderr)
        return

    # 4. LLM 출력 파싱 (정규 표현식 사용)
    # 패턴: (카테고리 A, 카테고리 B) - 괄호와 콤마를 포함한 모든 쌍을 찾음
    # LLM이 출력한 텍스트에서 튜플 형태의 문자열을 모두 추출
    
    # 정규식 패턴: 괄호 안에 (문자열, 문자열)이 있는 형태를 찾음
    # 주의: null과 한글 카테고리 모두 포함할 수 있도록 일반 문자열 패턴 사용
    pattern = re.compile(r'\((.*?)\s*,\s*(.*?)\)')
    
    parsed_relations = []
    
    # 찾은 모든 튜플 쌍을 순회
    for match in pattern.finditer(llm_output_raw):
        # 괄호 안의 두 그룹 (상위, 하위)을 추출하고 공백을 제거
        parent = match.group(1).strip()
        child = match.group(2).strip()
        
        # null (최상위) 처리
        if parent.lower() == 'null':
            parent = None
            
        if parent and child:
            parsed_relations.append([parent, child])
        elif parent is None and child:
            parsed_relations.append([None, child])
            
    if not parsed_relations:
        print(f"[오류] LLM 출력에서 유효한 계층 관계 튜플을 파싱할 수 없습니다. 원본 출력:\n{llm_output_raw}", file=sys.stderr)
        return
        
    # 5. 최종 JSON 저장
    with open(OUTPUT_HIERARCHY_FILE, 'w', encoding='utf-8') as f:
        json.dump(parsed_relations, f, ensure_ascii=False, indent=2)

    print(f"\n[완료] 총 {len(parsed_relations)}개의 계층 관계 튜플 생성 완료.")
    print(f"  > 계층 구조 JSON 저장: {OUTPUT_HIERARCHY_FILE}")


if __name__ == "__main__":
    generate_hierarchy_relations()