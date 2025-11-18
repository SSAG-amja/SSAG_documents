"""
이 스크립트를 실행하기 전에:
pip install requests beautifulsoup4 langchain-text-splitters
"""

import json
import os
import requests
from bs4 import BeautifulSoup
from collections import defaultdict
from langchain_text_splitters import RecursiveCharacterTextSplitter
import sys
from core.config import SOLAR_API_KEY
# -----------------------------
# 1. 설정
# -----------------------------

# [ 1. 입력 ] 처리할 PDF 파일 경로
try:
    file_path = sys.argv[1] # 명령줄 인자로 경로 받음
except IndexError:
    print("오류: 처리할 파일 경로를 명령줄 인자로 제공해야 합니다.", file=sys.stderr)
    sys.exit(1)

# API 키 및 엔드포인트
# 경고: 실제 실행 환경에서는 환경 변수를 사용하는 것이 더 안전합니다.
UPSTAGE_PARSE_ENDPOINT = "https://api.upstage.ai/v1/document-digitization"
SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"

# Solar API 직접 호출을 위한 헤더
SOLAR_LLM_HEADERS = {
    "Authorization": f"Bearer {SOLAR_API_KEY}",
    "Content-Type": "application/json"
}

# -----------------------------
# 2. LLM 프롬프트 정의
# -----------------------------

# 테이블/차트 HTML을 텍스트로 요약하는 프롬프트
PROMPT_TABLE_CHART = """다음은 기술 문서에서 추출한 HTML <table> 형식의 데이터입니다.
이 표의 핵심 내용을 요약하고, 표가 무엇을 나타내는지 설명해주세요.
표에 나타난 주요 수치나 경향을 언급하는 것이 좋습니다.
결과는 한두 문단의 요약된 텍스트로만 제공해주세요. HTML 코드를 반복하지 마세요.

[데이터]
{HTML_DATA}
"""

# 청크 텍스트를 요약하는 프롬프트 (새로 추가됨)
PROMPT_SUMMARY = """다음 텍스트는 문서의 일부에서 추출한 청크입니다.
이 텍스트의 핵심 내용을 3줄 이내의 간결한 문장으로 요약해주세요.
결과 외에 다른 설명이나 서론/결론은 포함하지 마세요.

[텍스트]
{CHUNK_TEXT}
"""

# -----------------------------
# 3. 함수 정의
# -----------------------------

def call_document_parse(input_file):
    """PDF/DOCX/PPTX 파일을 파싱하여 원본 JSON 객체를 반환합니다."""
    with open(input_file, "rb") as f:
        files = {"document": f}
        data = {
            "ocr": "force",
            "model": "document-parse"
        }
        headers = {"Authorization": f"Bearer {SOLAR_API_KEY}"}
        
        print(f"[Step 1] Upstage API로 파싱 요청 중...", file=sys.stderr)
        response = requests.post(
            UPSTAGE_PARSE_ENDPOINT,
            headers=headers,
            data=data,
            files=files
        )
    
    if response.status_code == 200:
        print(f"[Step 1] 파싱 완료.", file=sys.stderr)
        return response.json()
    else:
        error_text = response.text if response.text else "알 수 없는 API 에러"
        raise ValueError(f"[Step 1] API 호출 실패: HTTP {response.status_code}: {error_text}")

def structure_parsed_json(parsed_data, doc_id):
    """파싱된 JSON 객체를 받아, 정제된 재료 리스트를 반환합니다."""
    
    print(f"[Step 2] 텍스트 정제 및 구조화 시작...", file=sys.stderr)
    
    TEXT_CATEGORIES = {"paragraph", "heading1", "list", "caption", "equation"}
    RAW_FOR_LLM_CATEGORIES = {"table", "chart"}
    FIGURE_CATEGORY = {"figure"}

    all_elements = parsed_data.get("elements", [])
    structured_chunks = []

    for element in all_elements:
        category = element.get("category")
        
        if category not in TEXT_CATEGORIES and \
           category not in RAW_FOR_LLM_CATEGORIES and \
           category not in FIGURE_CATEGORY:
            continue
            
        chunk_data = {
            "doc_id": doc_id, 
            "page": element.get("page", 1),
            "chunk_id": element.get("id"),
            "category": category,
            "content_to_process": None
        }

        if category in TEXT_CATEGORIES:
            html_content = element["content"].get("html", "")
            soup = BeautifulSoup(html_content, 'html.parser')
            plain_text = soup.get_text(separator=" ", strip=True) 
            chunk_data["content_to_process"] = plain_text
        elif category in FIGURE_CATEGORY:
            html_content = element["content"].get("html", "")
            soup = BeautifulSoup(html_content, 'html.parser')
            img_tag = soup.find('img')
            ocr_text = img_tag['alt'].replace('\n', ' ').strip() if img_tag and img_tag.get('alt') else ""
            chunk_data["content_to_process"] = ocr_text
        elif category in RAW_FOR_LLM_CATEGORIES:
            chunk_data["content_to_process"] = element["content"].get("html")

        if chunk_data["content_to_process"]:
            structured_chunks.append(chunk_data)

    print(f"[Step 2] 정제 완료. {len(structured_chunks)}개 재료 생성.", file=sys.stderr)
    return structured_chunks

# --- [ 수정: task 인자를 받아 HTML 요약 또는 텍스트 요약 수행 ] ---
def call_solar_llm(content, task="table_chart"):
    """requests를 사용해 Solar LLM을 호출하여 HTML을 요약하거나 텍스트를 요약합니다."""
    
    # task에 따라 프롬프트 선택
    if task == "table_chart":
        formatted_prompt = PROMPT_TABLE_CHART.format(HTML_DATA=content)
    elif task == "summary":
        if not content or content.isspace(): # 내용이 없거나 공백만 있는 경우
            return ""
        formatted_prompt = PROMPT_SUMMARY.format(CHUNK_TEXT=content)
    else:
        return content # 알 수 없는 task일 경우 원본 내용 반환

    try:
        payload = {
            "model": "solar-pro2",
            "messages": [{"role": "user", "content": formatted_prompt}]
        }
        
        response = requests.post(
            SOLAR_LLM_ENDPOINT,
            headers=SOLAR_LLM_HEADERS,
            json=payload
        )
        response.raise_for_status()
        
        return response.json()['choices'][0]['message']['content'].strip()
        
    except Exception as e:
        print(f"  > [LLM Error] Solar 2 Pro 호출 실패 ({task}): {e}", file=sys.stderr)
        return f"[LLM 오류: {task} 처리 실패]"

# output_chunk_file 인자 제거
def group_and_chunk_by_page(structured_elements, doc_id): 
    """정제된 재료 리스트를 받아, 페이지 그룹핑, LLM 요약/변환을 수행하고 최종 청크 리스트를 stdout으로 출력합니다."""
    
    print(f"[Step 3] 페이지 그룹핑 및 LLM 처리 시작...", file=sys.stderr)
    
    pages_data = defaultdict(list)
    for el in structured_elements:
        pages_data[el["page"]].append(el)

    final_chunks_for_embedding = []
    MAX_CHUNK_CHAR_LENGTH = 1500 
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHUNK_CHAR_LENGTH, chunk_overlap=150,
        length_function=len, separators=["\n\n", "\n", " ", ""]
    )

    for page_num, page_elements in sorted(pages_data.items()):
        print(f"  - 페이지 {page_num} 처리 중...", file=sys.stderr)
        page_content_buffer = []
        for el in page_elements:
            category = el["category"]
            content = el["content_to_process"]
            
            # 테이블/차트는 LLM 요약으로 변환
            if category in ["table", "chart"]:
                processed_text = call_solar_llm(content, task="table_chart") # task='table_chart'
                if processed_text: page_content_buffer.append(f"[{category.upper()} 요약]: {processed_text}")
            # 일반 텍스트 및 이미지 OCR은 그대로 추가
            elif category in ["heading1", "paragraph", "list", "caption", "equation", "figure"]:
                if content: page_content_buffer.append(content)

        full_page_text = "\n\n".join(page_content_buffer).strip()

        if not full_page_text:
            continue
            
        full_document_content = full_page_text

        # 1. 페이지 전체가 청크 크기 제한을 초과하지 않는 경우 (단일 청크)
        if len(full_document_content) <= MAX_CHUNK_CHAR_LENGTH * 1.1:
            if full_document_content.strip():
                # --- [추가] 요약 생성 ---
                summary_text = call_solar_llm(full_document_content, task="summary")
                
                final_chunks_for_embedding.append({
                    "doc_id": doc_id, 
                    "page": page_num, 
                    "chunk_in_page": 0,
                    "text_for_embedding": full_document_content,
                    "summary": summary_text # <--- summary 필드 추가
                })
        # 2. 페이지를 분할해야 하는 경우
        else:
            print(f"    > 페이지 {page_num} 분할...", file=sys.stderr)
            # 문맥 없는 텍스트만 분할
            text_chunks = text_splitter.split_text(full_page_text)
            for i, chunk_text in enumerate(text_chunks):
                chunk_content = chunk_text # 순수한 내용만

                # --- [추가] 요약 생성 ---
                summary_text = call_solar_llm(chunk_content, task="summary")

                final_chunks_for_embedding.append({
                    "doc_id": doc_id, 
                    "page": page_num, 
                    "chunk_in_page": i,
                    "text_for_embedding": chunk_content,
                    "summary": summary_text # <--- summary 필드 추가
                })

    # 최종 청크 리스트를 JSON 문자열로 stdout에 출력
    print(json.dumps(final_chunks_for_embedding, ensure_ascii=False)) 

    print(f"\n[Step 3] 최종 청킹 완료! {len(final_chunks_for_embedding)}개 청크 생성.", file=sys.stderr)


# -----------------------------
# 4. 실행 (All-in-One)
# -----------------------------
if __name__ == "__main__":
    try:
        # file_path는 이미 위에서 sys.argv[1]로 설정됨
        if not os.path.exists(file_path):
            print(f"오류: PDF/DOCX/PPTX 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
            sys.exit(1)
        else:
            # 1. doc_id를 파일의 절대 경로로 설정 (고유성 보장)
            absolute_path = os.path.abspath(file_path)
            
            # 2. API 파싱 (메모리로 반환)
            parsed_data = call_document_parse(file_path)
            
            # 3. 텍스트 정제 (메모리로 반환)
            structured_data = structure_parsed_json(parsed_data, absolute_path)
            
            # 4. 그룹핑, LLM 처리, 및 최종 청크 stdout 출력
            group_and_chunk_by_page(structured_data, absolute_path)
            
            print("\n--- 전체 파이프라인 성공 ---", file=sys.stderr)

    except Exception as e:
        print(f"\n--- 파이프라인 실행 중 오류 발생 ---", file=sys.stderr)
        # LLM 호출 시 발생하는 HTTP/네트워크 오류를 포함한 모든 예외를 stderr에 출력
        print(e, file=sys.stderr)
        sys.exit(1)