"""
이 스크립트를 실행하기 전에:
pip install langchain-text-splitters requests
"""

import json
import os
import re  
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
import sys 
import requests # <--- 추가: LLM 호출을 위해 requests 모듈 추가

from core.config import SOLAR_API_KEY
# -----------------------------
# 1. 설정 (LLM API 설정 추가)
# -----------------------------

# [ 1. 입력 ] 처리할 코드 파일 경로
try:
    file_path = sys.argv[1] 
except IndexError:
    print("오류: 처리할 파일 경로를 명령줄 인자로 제공해야 합니다.", file=sys.stderr)
    sys.exit(1)

# [ 2. 출력 ] 최종 결과 파일 관련 변수는 제거
base_name = os.path.basename(file_path)
file_name_without_extension = os.path.splitext(base_name)[0]

MAX_CHUNK_CHAR_LENGTH = 2000 

LANGUAGE_MAP = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".java": Language.JAVA,
    ".c": Language.C,
    ".cpp": Language.CPP,
    ".go": Language.GO,
    ".rb": Language.RUBY,
    ".ts": Language.TS,
}

# API 키 및 엔드포인트
SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"

# Solar API 직접 호출을 위한 헤더
SOLAR_LLM_HEADERS = {
    "Authorization": f"Bearer {SOLAR_API_KEY}",
    "Content-Type": "application/json"
}

# -----------------------------
# 2. 코드 전체 요약 함수 (새로 추가)
# -----------------------------

def call_solar_code_summary(file_name: str, full_code: str) -> str:
    """Solar LLM을 호출하여 전체 코드 파일을 요약합니다. 파일 크기가 클 경우 중간 부분만 사용합니다."""
    
    # LLM 프롬프트에 들어갈 최대 텍스트 길이 (10,000자 제한)
    MAX_PROMPT_TEXT_LENGTH = 10000
    code_text = full_code
    
    # 1. 길이 체크 및 프롬프트 생성
    if len(code_text) > MAX_PROMPT_TEXT_LENGTH:
        # 코드가 너무 길면 중간 부분 10,000자만 추출
        start_index = (len(code_text) - MAX_PROMPT_TEXT_LENGTH) // 2
        end_index = start_index + MAX_PROMPT_TEXT_LENGTH
        
        truncated_content = code_text[start_index:end_index]
        print(f"[LLM] 파일 크기가 커서 코드의 중간 부분 (총 {MAX_PROMPT_TEXT_LENGTH}자)만 사용합니다.", file=sys.stderr)
        
        prompt = f"""다음은 파일 제목과 코드의 중간 부분입니다.
이 정보를 바탕으로 이 **{file_name}** 파일이 어떤 목적으로 작성되었는지, 주요 기능은 무엇인지 3문장 이내로 간결하게 요약해 주세요.
코드의 시작과 끝이 아니며 중간 부분만 포함되어 있음을 고려해 주세요.

[코드 정보]
---
파일 제목: {file_name}
내용:
{truncated_content}
---

코드 전체 요약:"""
    else:
        # 전체 코드 사용
        prompt = f"""다음은 파일 제목과 코드의 전체 내용입니다. 
이 **{file_name}** 파일이 어떤 목적으로 작성되었는지, 주요 기능은 무엇인지 3문장 이내로 간결하게 요약해 주세요.

[코드 전체 내용]
---
파일 제목: {file_name}
내용:
{code_text}
---

코드 전체 요약:"""
        
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
        print(f"[LLM] 코드 전체 요약 요청 중...", file=sys.stderr)
        response = requests.post(SOLAR_LLM_ENDPOINT, headers=SOLAR_LLM_HEADERS, json=payload, timeout=60)
        response.raise_for_status()
        
        response_json = response.json()
        summary = response_json['choices'][0]['message']['content'].strip()
        print(f"[LLM] 코드 요약 완료. (요약 길이: {len(summary)}자)", file=sys.stderr)
        return summary
        
    except (requests.exceptions.RequestException, KeyError, IndexError) as e:
        print(f"[LLM 요약 오류] 요청 실패 또는 응답 형식 오류: {e}", file=sys.stderr)
        return f"[코드 요약 실패: {file_name}]"


# -----------------------------
# 3. 코드 파일 처리 함수 (수정: 요약 생성 로직 추가)
# -----------------------------
def process_code_file(input_file, doc_id, file_name_prefix):
    
    file_extension = os.path.splitext(input_file)[1].lower()
    
    if file_extension not in LANGUAGE_MAP:
        print(f"오류: '{file_extension}'은(는) 지원하는 코드 형식이 아닙니다.", file=sys.stderr)
        return

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            full_code = f.read()
    except Exception as e:
        print(f"파일 읽기 중 오류 발생: {e}", file=sys.stderr)
        return

    print(f"\n[코드 처리] '{input_file}' 파일 처리 시작 (언어: {LANGUAGE_MAP[file_extension].value})...", file=sys.stderr)

    # 🌟 1. 문서 전체 요약 생성 (LLM 호출) 🌟
    document_summary = call_solar_code_summary(file_name_prefix, full_code)
    
    # 2. Langchain 언어별 분할기를 사용 (기존 로직)
    language_enum = LANGUAGE_MAP[file_extension]
    text_splitter = RecursiveCharacterTextSplitter.from_language(
        language=language_enum,
        chunk_size=MAX_CHUNK_CHAR_LENGTH,
        chunk_overlap=200,
        length_function=len
    )
    
    # 3. 코드를 분할
    code_chunks = text_splitter.split_text(full_code)
    
    if not code_chunks:
        print("파일 내용이 비어있어 처리를 중단합니다.", file=sys.stderr)
        return

    print(f"  > 코드를 총 {len(code_chunks)}개 청크로 분할했습니다. (후처리 시작...)", file=sys.stderr)

    # 4. 최종 JSON 형식으로 변환 (파일 제목 및 summary 포함)
    final_chunks_for_embedding = []
    for i, chunk_text in enumerate(code_chunks):
        
        # --- [기존 로직: 후처리(Post-processing)] ---
        cleaned_chunk = re.sub(r'\n\s*\n+', '\n', chunk_text)
        cleaned_chunk = re.sub(r' {2,}', ' ', cleaned_chunk)
        # --- [수정 종료] ---

        final_text_to_embed = f"파일 제목: {file_name_prefix}\n\n코드 내용:\n{cleaned_chunk}" 
        
        final_chunks_for_embedding.append({
            "doc_id": doc_id,
            "page": 1,
            "chunk_in_page": i,
            "text_for_embedding": final_text_to_embed,
            "summary": document_summary # <--- 💡 문서 전체 요약 추가
        })

    # <--- 핵심 수정: 최종 청크 리스트를 JSON 문자열로 stdout에 출력
    print(json.dumps(final_chunks_for_embedding, ensure_ascii=False))
    
    # 로그는 stderr로 출력
    print(f"\n[코드 처리] 최종 청킹 완료! (후처리 적용) {len(code_chunks)}개 청크 생성.", file=sys.stderr)

# -----------------------------
# 4. 실행 (기존 로직 유지)
# -----------------------------
if __name__ == "__main__":
    try:
        if not os.path.exists(file_path):
            print(f"오류: 입력 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
            sys.exit(1)
        else:
            absolute_path = os.path.abspath(file_path)

            process_code_file(
                input_file=file_path,
                doc_id=absolute_path,
                file_name_prefix=file_name_without_extension
            )
            print("\n--- 전체 파이프라인 성공 ---", file=sys.stderr)

    except Exception as e:
        print(f"\n--- 파이프라인 실행 중 오류 발생 ---", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)