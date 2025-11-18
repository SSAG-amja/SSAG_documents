"""
이 스크립트를 실행하기 전에:
pip install beautifulsoup4 langchain-text-splitters requests
이건 html 전용
"""

import json
import os
from bs4 import BeautifulSoup, NavigableString, Comment  
from langchain_text_splitters import RecursiveCharacterTextSplitter
import sys 
import requests # <--- 추가: LLM 호출을 위해 requests 모듈 추가
from core.config import SOLAR_API_KEY
# -----------------------------
# 1. 설정 (LLM API 설정 추가)
# -----------------------------

# [ 1. 입력 ] 처리할 HTML 파일 경로
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
# 2. HTML 정제 함수 (기존 유지)
# -----------------------------
def clean_html_content(html_body):
    """
    BeautifulSoup을 사용해 HTML에서 불필요한 태그를 모두 제거하고,
    본문 텍스트만 추출합니다.
    """
    
    JUNK_TAGS = [
        'script', 'style', 'nav', 'header', 'footer', 
        'aside', 'form', 'button', 'iframe', 'svg'
    ]
    
    soup = BeautifulSoup(html_body, 'html.parser')

    # 1. 모든 정크 태그 제거
    for tag in soup(JUNK_TAGS):
        tag.decompose() 

    # 2. 주석(Comments) 제거
    for element in soup(text=lambda text: isinstance(text, Comment)):
        element.extract()

    # 3. 정제된 텍스트 추출
    clean_text = soup.get_text(separator='\n', strip=True)
    
    return clean_text


# -----------------------------
# 3. 문서 전체 요약 함수 (새로 추가)
# -----------------------------

def call_solar_html_summary(file_name: str, full_text: str) -> str:
    """Solar LLM을 호출하여 HTML 파일의 정제된 텍스트 전체를 요약합니다. 파일 크기가 클 경우 중간 부분만 사용합니다."""
    
    # LLM 프롬프트에 들어갈 최대 텍스트 길이 (10,000자 제한)
    MAX_PROMPT_TEXT_LENGTH = 10000
    text_content = full_text
    
    # 1. 길이 체크 및 프롬프트 생성
    if len(text_content) > MAX_PROMPT_TEXT_LENGTH:
        # 텍스트가 너무 길면 중간 부분 10,000자만 추출
        start_index = (len(text_content) - MAX_PROMPT_TEXT_LENGTH) // 2
        end_index = start_index + MAX_PROMPT_TEXT_LENGTH
        
        truncated_content = text_content[start_index:end_index]
        print(f"[LLM] 파일 크기가 커서 정제된 텍스트의 중간 부분 (총 {MAX_PROMPT_TEXT_LENGTH}자)만 사용합니다.", file=sys.stderr)
        
        prompt = f"""다음은 HTML 파일에서 정제된 텍스트의 중간 부분입니다.
이 정보를 바탕으로 이 **{file_name}** 파일이 어떤 내용을 담고 있는지, 핵심 주제는 무엇인지 3문장 이내로 간결하게 요약해 주세요.
텍스트의 시작과 끝이 아니며 중간 부분만 포함되어 있음을 고려해 주세요.

[정제된 텍스트 정보]
---
파일 제목: {file_name}
내용:
{truncated_content}
---

문서 전체 요약:"""
    else:
        # 전체 텍스트 사용
        prompt = f"""다음은 HTML 파일에서 정제된 텍스트의 전체 내용입니다. 
이 **{file_name}** 파일이 어떤 목적으로 작성되었는지, 주요 기능은 무엇인지 3문장 이내로 간결하게 요약해 주세요.

[정제된 텍스트 전체 내용]
---
파일 제목: {file_name}
내용:
{text_content}
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
        return f"[문서 요약 실패: {file_name}]"

# -----------------------------
# 4. HTML 파일 처리 함수 (수정: 요약 생성 로직 추가)
# -----------------------------
def process_html_file(input_file, doc_id, file_name_prefix): 
    """
    HTML 파일을 읽어, 정제(Clean)하고, 문서 전체를 요약한 뒤, 청크 단위로 분할하여,
    최종 임베딩용 JSON을 stdout으로 출력합니다.
    """
    
    try:
        # 파일 인코딩 처리
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                full_html = f.read()
        except UnicodeDecodeError:
            with open(input_file, "r", encoding="latin-1") as f:
                full_html = f.read()
                
    except Exception as e:
        print(f"파일 읽기 중 오류 발생: {e}", file=sys.stderr)
        return

    print(f"\n[HTML 처리] '{input_file}' 파일 처리 시작...", file=sys.stderr)

    # 1. HTML 정제
    print("  > HTML 정제 중 (스크립트, 스타일, 네비게이션 태그 제거)...", file=sys.stderr)
    body_text = clean_html_content(full_html)
    
    if not body_text.strip():
        print("파일 내용이 비어있거나, 본문 텍스트가 없어 처리를 중단합니다.", file=sys.stderr)
        return

    # 🌟 2. 문서 전체 요약 생성 (LLM 호출) 🌟
    document_summary = call_solar_html_summary(file_name_prefix, body_text)

    # 3. 텍스트 분할기
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_CHAR_LENGTH,
        chunk_overlap=150,
        length_function=len,
        separators=["\n\n", "\n", " ", ""]
    )

    # 4. "정제된 텍스트"를 청크로 분할
    text_chunks = text_splitter.split_text(body_text)
    
    if not text_chunks:
        print("파일 내용이 비어있거나, 본문 텍스트가 없어 처리를 중단합니다.", file=sys.stderr)
        return

    print(f"  > 정제된 텍스트를 총 {len(text_chunks)}개 청크로 분할했습니다.", file=sys.stderr)

    # 5. 최종 JSON 형식으로 변환 (파일 제목 및 summary 포함)
    final_chunks_for_embedding = []
    for i, chunk_text in enumerate(text_chunks):
        
        final_text_to_embed = f"파일 제목: {file_name_prefix}\n\n내용: {chunk_text}"
        
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
    print(f"\n[HTML 처리] 최종 청킹 완료! (파일 제목 포함) {len(text_chunks)}개 청크 생성.", file=sys.stderr)

# -----------------------------
# 5. 실행 (기존 로직 유지)
# -----------------------------
if __name__ == "__main__":
    try:
        if not os.path.exists(file_path):
            print(f"오류: 입력 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
            sys.exit(1)
        else:
            absolute_path = os.path.abspath(file_path)

            process_html_file(
                input_file=file_path,
                doc_id=absolute_path,
                file_name_prefix=file_name_without_extension
            )
            print("\n--- 전체 파이프라인 성공 ---", file=sys.stderr)
            
    except Exception as e:
        print(f"\n--- 파이프라인 실행 중 오류 발생 ---", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)