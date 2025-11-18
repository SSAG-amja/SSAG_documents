import os
import subprocess
import json
import tempfile
import sys
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# --- 설정 (스크립트 파일 경로) ---
# 전처리 스크립트가 있는 디렉토리 (상대 경로: ../typeJson)
TYPEJSON_DIR = os.path.join(CURRENT_DIR, "..", "typeClass")
# 임베딩 스크립트가 있는 디렉토리 (상대 경로: ../embedding)
EMBEDDING_DIR = os.path.join(CURRENT_DIR, "..", "embedding")

# 전처리 스크립트 경로 설정
DOCTYPE1_SCRIPT = os.path.join(TYPEJSON_DIR, "doctype1.py")
DOCTYPE2_SCRIPT = os.path.join(TYPEJSON_DIR, "doctype2.py")
CODETYPE1_SCRIPT = os.path.join(TYPEJSON_DIR, "codetype1.py")
CODETYPE2_SCRIPT = os.path.join(TYPEJSON_DIR, "codetype2.py")
TABLETYPE1_SCRIPT = os.path.join(TYPEJSON_DIR, "tabletype1.py")

# 임베딩 스크립트 경로 설정
EMBED_SCRIPT = os.path.join(EMBEDDING_DIR, "runEmbed.py")
# --- 파일 확장자별 스크립트 매핑 ---
FILE_TYPE_MAP = {
    ('.pdf', '.docx', '.pptx', '.doc'): DOCTYPE1_SCRIPT,
    ('.txt'): DOCTYPE2_SCRIPT,
    ('.py', '.js', '.java', '.c', '.cpp', '.go', '.rb', '.ts'): CODETYPE1_SCRIPT,
    ('.html', '.htm'): CODETYPE2_SCRIPT,
    ('.xlsx', '.xls', '.csv'): TABLETYPE1_SCRIPT
}

def get_processor_script(file_path):
    """파일 확장자를 기반으로 적절한 전처리 스크립트를 반환합니다."""
    ext = os.path.splitext(file_path)[1].lower()
    for extensions, script in FILE_TYPE_MAP.items():
        if ext in extensions:
            return script
    return None

def execute_preprocess_script(script_path, file_path):
    """
    외부 전처리 스크립트를 실행하고, stdout에서 JSON 텍스트(청크 리스트)를 파싱합니다.
    """
    print(f"\n  🚀 전처리 실행: {os.path.basename(script_path)}", file=sys.stderr)
    try:
        # 전처리 스크립트 실행 및 stdout 캡처
        process = subprocess.Popen(
            ["python", script_path, file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, # 전처리 스크립트의 로그는 stderr로 출력되도록 설계
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate()
        
        # 전처리 스크립트가 0이 아닌 코드를 반환하거나, stdout이 비어있으면 오류
        if process.returncode != 0:
            print(f"  ❌ 전처리 오류 (Code: {process.returncode}): {os.path.basename(script_path)}", file=sys.stderr)
            print(f"  --- STDERR LOG --- \n{stderr}", file=sys.stderr)
            return False, f"전처리 실패: {stderr}"
        
        if not stdout.strip():
             return True, [] # 청크가 0개인 경우 (정상 종료)

        # stdout에서 JSON 파싱
        print(f"  ✅ 전처리 성공: {os.path.basename(script_path)}", file=sys.stderr)
        return True, json.loads(stdout.strip())
            
    except json.JSONDecodeError:
        print("  ❌ 오류: 전처리 스크립트 출력이 유효한 JSON 형식이 아닙니다.", file=sys.stderr)
        print(f"  파싱 실패 원본 출력 (일부): {stdout[:500]}...", file=sys.stderr)
        return False, "JSON 파싱 오류"
    except Exception as e:
        print(f"  ❌ 오류: 실행 중 예외 발생: {e}", file=sys.stderr)
        return False, str(e)

def execute_embed_script(temp_json_path, starting_global_id):
    """
    임베딩 스크립트를 호출하고, Qdrant ID를 전달합니다.
    """
    print(f"  🚀 임베딩 실행: {os.path.basename(EMBED_SCRIPT)} (시작 ID: {starting_global_id})", file=sys.stderr)
    try:
        # 임베딩 스크립트에 임시 파일 경로와 시작 ID를 인자로 전달
        process = subprocess.Popen(
            ["python", EMBED_SCRIPT, temp_json_path, str(starting_global_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        stdout, stderr = process.communicate()

        # 성공 여부는 반환 코드(0)와 stdout의 "EMBEDDING_SUCCESS" 메시지로 판단
        if process.returncode == 0 and "EMBEDDING_SUCCESS" in stdout:
            print(f"  ✅ 임베딩 성공: {os.path.basename(EMBED_SCRIPT)}", file=sys.stderr)
            return True, None
        else:
            print(f"  ❌ 임베딩 오류 (Code: {process.returncode}): {os.path.basename(EMBED_SCRIPT)}", file=sys.stderr)
            print(f"  --- STDERR LOG --- \n{stderr}", file=sys.stderr)
            return False, f"임베딩 실패: {stderr}"
            
    except Exception as e:
        print(f"  ❌ 오류: 임베딩 실행 중 예외 발생: {e}", file=sys.stderr)
        return False, str(e)


def run_pipeline(file_paths):
    """
    중앙 파이프라인 로직: 파일별로 전처리 -> 임베딩을 순차적으로 수행합니다.
    """
    print("--- RAG 데이터 전처리 및 임베딩 파이프라인 시작 ---", file=sys.stderr)
    
    overall_status = {}
    # 2. 연속적인 Qdrant ID 관리를 위한 카운터 (Qdrant ID는 1부터 시작)
    current_qdrant_id = 1 
    
    for file_path in file_paths:
        file_name = os.path.basename(file_path)
        print(f"\n=======================================================", file=sys.stderr)
        print(f"  [파일 처리] {file_name} (다음 Qdrant 시작 ID: {current_qdrant_id})", file=sys.stderr)
        print(f"=======================================================", file=sys.stderr)
        
        processor_script = get_processor_script(file_path)
        
        if not processor_script:
            print(f"⚠️ 경고: 지원하지 않는 파일 형식. 건너뜀.", file=sys.stderr)
            overall_status[file_name] = {"status": "SKIP", "message": "지원하지 않는 형식"}
            continue
            
        # 1. 파일 전처리 (JSON 문자열을 메모리(result_data)로 획득)
        preprocess_success, result_data = execute_preprocess_script(processor_script, file_path)
        
        # 전처리 성공 및 청크가 존재하는 경우
        if preprocess_success and isinstance(result_data, list) and result_data:
            chunks = result_data
            num_chunks = len(chunks)
            temp_json_path = None
            
            try:
                # 2. 전처리된 청크 리스트를 임시 파일에 저장
                with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.json') as tmp_file:
                    json.dump(chunks, tmp_file, ensure_ascii=False, indent=2)
                    temp_json_path = tmp_file.name
                
                print(f"  > 임시 JSON 생성: {temp_json_path} (청크 {num_chunks}개)", file=sys.stderr)
                
                # 3. 임베딩 및 Qdrant 색인
                embed_success, embed_message = execute_embed_script(temp_json_path, current_qdrant_id)

                if embed_success:
                    # ✅ 임베딩 성공 시, 다음 파일의 시작 ID 업데이트
                    current_qdrant_id += num_chunks
                    overall_status[file_name] = {"status": "SUCCESS", "message": f"전처리 및 임베딩 완료 (총 {num_chunks}개 청크)"}
                else:
                    overall_status[file_name] = {"status": "FAIL", "message": embed_message}
                    
            except Exception as e:
                 overall_status[file_name] = {"status": "FAIL", "message": f"임시 파일 또는 임베딩 처리 중 예외 발생: {e}"}
            finally:
                # 4. 임시 파일 삭제
                if temp_json_path and os.path.exists(temp_json_path):
                    os.remove(temp_json_path)
                    print(f"  > 임시 파일 삭제: {temp_json_path}", file=sys.stderr)

        elif preprocess_success and not result_data:
             print(f"  > 전처리 성공했으나, 생성된 청크가 0개입니다. 건너뜁니다.", file=sys.stderr)
             overall_status[file_name] = {"status": "SKIP", "message": "생성된 청크 0개"}
        else:
            # 전처리 실패 시, result_data는 에러 메시지 문자열
            overall_status[file_name] = {"status": "FAIL", "message": result_data}

    print("\n--- 파이프라인 종료 (결과 요약) ---", file=sys.stderr)
    for file, status in overall_status.items():
        print(f"- {file}: **{status['status']}** - {status['message']}", file=sys.stderr)
        
    return overall_status

