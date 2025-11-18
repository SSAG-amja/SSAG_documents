"""
이 스크립트를 실행하기 전에:
pip install langchain-text-splitters requests
"""

import json
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
import sys 
import requests # <--- 추가: LLM 호출을 위해 requests 모듈 추가
from core.config import SOLAR_API_KEY
# -----------------------------
# 1. 설정 (LLM API 설정 추가)
# -----------------------------

# [ 1. 입력 ] 처리할 텍스트 파일 경로
try:
    file_path = sys.argv[1] 
except IndexError:
    print("오류: 처리할 파일 경로를 명령줄 인자로 제공해야 합니다.", file=sys.stderr)
    sys.exit(1)

# [ 2. 출력 ] 최종 결과 파일 관련 변수는 제거
base_name = os.path.basename(file_path)
file_name_without_extension = os.path.splitext(base_name)[0]

MAX_CHUNK_CHAR_LENGTH = 1500 

# API 키 및 엔드포인트
SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"

# Solar API 직접 호출을 위한 헤더
SOLAR_LLM_HEADERS = {
    "Authorization": f"Bearer {SOLAR_API_KEY}",
    "Content-Type": "application/json"
}

# -----------------------------
# 2. 문서 전체 요약 함수 (새로 추가)
# -----------------------------

def call_solar_file_summary(file_name: str, full_text: str) -> str:
    """Solar LLM을 호출하여 전체 파일을 요약합니다. 파일 크기가 클 경우 일부만 사용합니다."""
    
    # LLM 프롬프트에 들어갈 최대 텍스트 길이 (10,000자 제한)
    MAX_PROMPT_TEXT_LENGTH = 1500
    
    # 파일 제목 포함
    prompt_text = f"문서 제목: {file_name}\n\n내용:\n{full_text}"
    
    # 1. 길이 체크 및 프롬프트 생성
    if len(prompt_text) > MAX_PROMPT_TEXT_LENGTH:
        # 텍스트가 너무 길면 앞부분만 사용
        truncated_content = prompt_text[:MAX_PROMPT_TEXT_LENGTH]
        print(f"[LLM] 파일 크기가 커서 텍스트 앞 {MAX_PROMPT_TEXT_LENGTH}자만 사용합니다.", file=sys.stderr)
        
        prompt = f"""다음은 문서의 제목과 내용의 시작 부분입니다.
이 정보를 바탕으로 문서 전체의 주제와 핵심 내용을 3문장 이내로 간결하게 요약해 주세요.

[문서 정보]
---
{truncated_content}
---

문서 전체 요약:"""
    else:
        # 전체 텍스트 사용
        prompt = f"""다음은 문서의 전체 내용입니다. 
이 문서의 주제와 핵심 내용을 3문장 이내로 간결하게 요약해 주세요.

[문서 전체 내용]
---
{prompt_text}
---

문서 전체 요약:"""
        
    # 2. LLM 호출
    payload = {
        "model": "solar-pro2", 
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 512
    }
    
    try:
        print(f"[LLM] 문서 전체 요약 요청 중...", file=sys.stderr)
        response = requests.post(SOLAR_LLM_ENDPOINT, headers=SOLAR_LLM_HEADERS, json=payload, timeout=60)
        response.raise_for_status()
        
        response_json = response.json()
        summary = response_json['choices'][0]['message']['content'].strip()
        print(f"[LLM] 문서 요약 완료. (요약 길이: {len(summary)}자)", file=sys.stderr)
        return summary
        
    except (requests.exceptions.RequestException, KeyError, IndexError) as e:
        print(f"[LLM 요약 오류] 요청 실패 또는 응답 형식 오류: {e}", file=sys.stderr)
        # 오류 발생 시 기본값 반환
        return f"[문서 요약 실패: {file_name}]"

# -----------------------------
# 3. 텍스트 파일 처리 함수 (수정: 요약 생성 로직 추가)
# -----------------------------
def process_text_file(input_file, doc_id, file_name_prefix):
    """
    텍스트 파일을 읽어, 문서 전체를 요약하고 청크 단위로 분할하여,
    최종 임베딩용 JSON을 stdout으로 출력합니다.
    """
    
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            full_text = f.read()
    except FileNotFoundError:
        print(f"오류: '{input_file}'을 찾을 수 없습니다.", file=sys.stderr)
        return
    except Exception as e:
        print(f"파일 읽기 오류: {e}", file=sys.stderr)
        return

    if not full_text.strip():
        print(f"오류: '{input_file}'의 내용이 비어있어 처리를 중단합니다.", file=sys.stderr)
        return

    # 🌟 1. 문서 전체 요약 생성 (LLM 호출) 🌟
    document_summary = call_solar_file_summary(file_name_prefix, full_text)
    
    # 2. 청크 분할 (기존 로직)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_CHAR_LENGTH, chunk_overlap=150,
        length_function=len, separators=["\n\n", "\n", " ", ""]
    )
    text_chunks = text_splitter.split_text(full_text)
    
    if not text_chunks:
        print(f"오류: 텍스트 분할 결과 청크가 없어 처리를 중단합니다.", file=sys.stderr)
        return

    print(f"  > 텍스트를 총 {len(text_chunks)}개 청크로 분할했습니다.", file=sys.stderr)

    # 3. 최종 JSON 형식으로 변환 (summary 필드 추가)
    final_chunks_for_embedding = []
    for i, chunk_text in enumerate(text_chunks):
        
        final_text_to_embed = f"파일 제목: {file_name_prefix}\n\n내용: {chunk_text}"
        
        final_chunks_for_embedding.append({
            "doc_id": doc_id,
            "page": 1,
            "chunk_in_page": i,
            "text_for_embedding": final_text_to_embed,
            "summary": document_summary # <--- 💡 문서 전체 요약을 모든 청크에 추가
        })

    # <--- 핵심 수정: 최종 청크 리스트를 JSON 문자열로 stdout에 출력
    print(json.dumps(final_chunks_for_embedding, ensure_ascii=False)) 
    
    # 로그는 stderr로 출력
    print(f"\n[텍스트 처리] 최종 청킹 완료! (파일 제목 포함) {len(final_chunks_for_embedding)}개 청크 생성.", file=sys.stderr)

# -----------------------------
# 4. 실행 (기존 로직 유지)
# -----------------------------
if __name__ == "__main__":
    try:
        if not os.path.exists(file_path):
            print(f"오류: 텍스트 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
            sys.exit(1)
        
        # doc_id를 파일의 절대 경로로 설정
        absolute_path = os.path.abspath(file_path)
            
        # file_name_without_extension는 전역 스코프에서 이미 정의됨
        process_text_file(file_path, absolute_path, file_name_without_extension)
            
        print("\n--- 전체 파이프라인 성공 ---", file=sys.stderr)

    except Exception as e:
        print(f"\n--- 파이프라인 실행 중 오류 발생 ---", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)