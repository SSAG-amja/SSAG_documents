"""
이 스크립트를 실행하기 전에:
pip install pandas openpyxl requests
xlsx,csv
"""

import pandas as pd
import json
import os
import requests
from io import StringIO
from collections import defaultdict
import sys 
from core.config import SOLAR_API_KEY

# -----------------------------
# 1. 설정 (기존 유지)
# -----------------------------

# [ 1. 입력 ] 처리할 데이터 파일 경로 (CSV, XLSX 중 하나)
try:
    file_path = sys.argv[1] 
except IndexError:
    # 에러 메시지는 stderr로 출력
    print("오류: 처리할 파일 경로를 명령줄 인자로 제공해야 합니다.", file=sys.stderr)
    sys.exit(1)

# [ 2. 출력 ] 최종 청크 파일 관련 변수는 제거
base_name = os.path.basename(file_path)
file_name_prefix = os.path.splitext(base_name)[0]


SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
SOLAR_LLM_HEADERS = {
    "Authorization": f"Bearer {SOLAR_API_KEY}",
    "Content-Type": "application/json"
}

ROWS_PER_CHUNK = 5 # 상세 청크당 묶을 행의 개수

# -----------------------------
# 2. LLM 프롬프트 및 호출 함수 (기존 유지)
# -----------------------------

PROMPT_DATA_SUMMARY = """
당신은 데이터 분석 전문가입니다. 다음의 메타데이터와 샘플 데이터를 분석하여 파일 전체의 내용과 목적을 2~3문장으로 요약하세요.

[파일 메타데이터]
- 파일 제목: {FILE_TITLE}
- 열 이름 목록: {COLUMN_NAMES}

[데이터 샘플 (헤더 포함)]
{DATA_SAMPLE}
"""

def call_solar_llm_for_data_summary(file_name_prefix, column_names_str, data_sample_text):
    """
    Solar LLM을 호출하여 데이터 파일의 전체 내용을 요약합니다.
    """
    try:
        print(f"    > Solar LLM 호출 중... (데이터 요약)", file=sys.stderr)
        formatted_prompt = PROMPT_DATA_SUMMARY.format(
            FILE_TITLE=file_name_prefix,
            COLUMN_NAMES=column_names_str,
            DATA_SAMPLE=data_sample_text
        )
        
        payload = {
            "model": "solar-pro2",
            "messages": [{"role": "user", "content": formatted_prompt}]
        }
        
        # API 호출
        response = requests.post(SOLAR_LLM_ENDPOINT, headers=SOLAR_LLM_HEADERS, json=payload)
        response.raise_for_status() 
        
        return response.json()['choices'][0]['message']['content']
        
    except Exception as e:
        print(f"  > [LLM Error] Solar LLM 요약 호출 실패: {e}", file=sys.stderr)
        return f"[LLM 오류: 데이터 요약 실패]"


# -----------------------------
# 3. 데이터 처리 메인 함수 (수정: summary 필드 추가)
# -----------------------------

def process_data_file(input_file, doc_id): 
    
    file_extension = os.path.splitext(input_file)[1].lower()
    base_name = os.path.basename(input_file)
    file_name_prefix = os.path.splitext(base_name)[0]
    
    df = None
    final_chunks = []
    
    # 1. 파일 로드
    try:
        if file_extension == '.csv':
            df = pd.read_csv(input_file)
        elif file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(input_file, engine='openpyxl')
        else:
            print(f"오류: 지원하지 않는 데이터 파일 형식입니다.", file=sys.stderr)
            return
    except Exception as e:
        print(f"오류: 파일을 pandas로 로드하는 데 실패했습니다. {e}", file=sys.stderr)
        return

    print(f"\n[데이터 처리] '{base_name}' 로드 성공. (총 {len(df)} 행)", file=sys.stderr)

    # 1-1. LLM에게 전달할 메타데이터 준비 (열 이름 추출)
    column_names = df.columns.tolist()
    column_names_str = ", ".join(column_names)
    print(f"  > 추출된 열 이름: {column_names_str}", file=sys.stderr)


    # --- Layer 1: 요약 청크 (Chunk 0) ---
    
    # 2. 샘플 추출 및 CSV 변환
    sample_df = df.head(ROWS_PER_CHUNK)
    csv_buffer = StringIO()
    sample_df.to_csv(csv_buffer, index=False)
    data_sample_text = csv_buffer.getvalue()

    # 3. LLM 요약 호출
    llm_summary_text = call_solar_llm_for_data_summary(file_name_prefix, column_names_str, data_sample_text)
    
    # 4. Chunk 0 (요약) 최종 저장 (summary 필드 추가)
    final_chunks.append({
        "doc_id": doc_id, 
        "page": 1, 
        "chunk_in_page": 0, 
        "text_for_embedding": f"파일 제목: {file_name_prefix}\n\n[데이터 전체 요약]\n{llm_summary_text}",
        "summary": llm_summary_text # <--- 💡 summary 필드 추가 (요약 청크) 💡
    })
    print(f"[Layer 1] 요약 청크 (Chunk 0) 생성 완료.", file=sys.stderr)

    # --- Layer 2: 상세 블록 청크 (Chunk 1+) ---

    num_rows = len(df)
    
    # 5. 5행 단위(ROWS_PER_CHUNK)로 반복하며 블록 청크 생성
    for i in range(0, num_rows, ROWS_PER_CHUNK):
        chunk_df = df.iloc[i:i + ROWS_PER_CHUNK]
        chunk_index = i // ROWS_PER_CHUNK + 1 
        
        # 6. 블록 데이터를 CSV 텍스트로 직렬화
        csv_buffer = StringIO()
        
        # 첫 번째 상세 청크(Chunk 1)에만 헤더를 포함
        include_header = (i == 0) 
        
        chunk_df.to_csv(csv_buffer, index=False, header=include_header)
        data_block_text = csv_buffer.getvalue().strip()
        
        # 7. 최종 텍스트 포맷
        final_text_to_embed = f"파일 제목: {file_name_prefix}\n\n[데이터 블록 {chunk_index} (행 {i+1}~{min(i+ROWS_PER_CHUNK, num_rows)})]\n{data_block_text}"
        
        # 8. Chunk 1+ (상세) 최종 저장 (summary 필드 추가)
        final_chunks.append({
            "doc_id": doc_id,
            "page": 1, 
            "chunk_in_page": chunk_index,
            "text_for_embedding": final_text_to_embed,
            "summary": llm_summary_text # <--- 💡 summary 필드 추가 (상세 청크) 💡
        })
    
    print(f"[Layer 2] 상세 블록 청크 ({len(final_chunks) - 1}개) 생성 완료.", file=sys.stderr)
    
    # <--- 핵심 수정: 최종 청크 리스트를 JSON 문자열로 stdout에 출력
    print(json.dumps(final_chunks, ensure_ascii=False)) 
    
    print(f"\n[최종] 총 {len(final_chunks)}개 청크 생성 완료.", file=sys.stderr)


# -----------------------------
# 4. 실행 (기존 유지)
# -----------------------------
if __name__ == "__main__":
    try:
        if not os.path.exists(file_path):
            print(f"오류: 입력 파일을 찾을 수 없습니다: {file_path}", file=sys.stderr)
        else:
            # doc_id를 파일의 절대 경로로 설정 (고유성 보장)
            absolute_path = os.path.abspath(file_path)
            
            # 데이터 처리 함수 실행
            process_data_file(
                input_file=file_path,
                doc_id=absolute_path 
            )
            print("\n--- 전체 파이프라인 성공 ---", file=sys.stderr)
            
    except Exception as e:
        print(f"\n--- 파이프라인 실행 중 오류 발생 ---", file=sys.stderr)
        print(e, file=sys.stderr)
        sys.exit(1)