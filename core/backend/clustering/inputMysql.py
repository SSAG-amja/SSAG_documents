import mysql.connector
import json
import os

from core.config import MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_USER

# --- 설정 ---
DB_CONFIG = {
    "user": MYSQL_USER,          
    "password": MYSQL_PASSWORD,  
    "host": MYSQL_HOST,
    "database": MYSQL_DB 
}

# JSON 파일 이름 정의
HIERARCHY_JSON_NAME = "final_hierarchy_relations.json"
FILE_CLUSTER_JSON_NAME = "hdbscan_cluster_labels.json" # 파일 이름과 경로가 담긴 JSON

# --- 유틸리티 함수 ---

def load_json_data(file_name):
    """
    지정된 JSON 파일을 열어 데이터를 로드합니다.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name)
    
    try:
        print(f"\n--- JSON 파일 로드 시도: {file_name} ({file_path}) ---")
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            print("JSON 파일 로드 성공.")
            return data
    except FileNotFoundError:
        print(f"오류: 파일을 찾을 수 없습니다. 경로를 확인해주세요: {file_path}")
        return None
    except json.JSONDecodeError:
        print("오류: JSON 파일 형식이 올바르지 않습니다.")
        return None
    except Exception as e:
        print(f"파일 로드 중 알 수 없는 오류 발생: {e}")
        return None


# --- 1단계: category 테이블 삽입 함수 (변경 없음) ---

def insert_hierarchy_categories_from_file(config, hierarchy_data):
    """
    주어진 계층 구조 데이터를 MySQL category 테이블에 삽입합니다.
    (루트 카테고리 우선 처리 로직 포함)
    """
    if not hierarchy_data:
        print("삽입할 카테고리 데이터가 없습니다. 작업을 종료합니다.")
        return

    conn = None
    cursor = None
    category_map = {} # 카테고리 이름 -> category_id 매핑 딕셔너리

    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        
        print("\n--- 카테고리 계층 구조 삽입 시작 (루트 우선 처리) ---")

        # 1. 모든 고유 카테고리 이름을 추출하고, 루트 카테고리를 식별
        all_category_names = set()
        root_names = set()
        
        for parent_name, child_name in hierarchy_data:
            if parent_name is None:
                root_names.add(child_name)
            if parent_name:
                all_category_names.add(parent_name)
            all_category_names.add(child_name)

        # 2. 루트 카테고리를 먼저 삽입/조회합니다 (parent_id = NULL)
        print(f"\n--- 루트 카테고리 ({len(root_names)}개) 우선 처리 ---")
        for name in root_names:
            if name in category_map: continue
            cursor.execute("SELECT category_id FROM category WHERE category_name = %s", (name,))
            result = cursor.fetchone()
            if result:
                category_map[name] = result[0]
            else:
                insert_sql = "INSERT INTO category (category_name, parent_id) VALUES (%s, NULL)"
                cursor.execute(insert_sql, (name,))
                category_map[name] = cursor.lastrowid
                print(f"  새 루트 카테고리 삽입: '{name}' (ID: {category_map[name]})")

        # 3. 나머지 모든 고유 카테고리를 삽입/조회합니다.
        print(f"\n--- 나머지 {len(all_category_names) - len(root_names)}개 카테고리 처리 ---")
        for name in all_category_names:
            if name in category_map: continue
            cursor.execute("SELECT category_id FROM category WHERE category_name = %s", (name,))
            result = cursor.fetchone()
            if result:
                category_map[name] = result[0]
            else:
                insert_sql = "INSERT INTO category (category_name, parent_id) VALUES (%s, NULL)"
                cursor.execute(insert_sql, (name,))
                category_map[name] = cursor.lastrowid
                print(f"  새 카테고리 임시 삽입: '{name}' (ID: {category_map[name]})")

        # 4. JSON 데이터를 반복하며 상위-하위 관계를 설정 (parent_id 업데이트)
        print("\n--- 상위-하위 관계 설정 (parent_id 업데이트) ---")
        for parent_name, child_name in hierarchy_data:
            if parent_name is None: continue
            
            parent_id = category_map.get(parent_name)
            child_id = category_map.get(child_name)
            
            if parent_id is None or child_id is None:
                print(f"경고: 관계 설정 실패 - '{parent_name}' 또는 '{child_name}'의 ID를 찾을 수 없음.")
                continue

            # 하위 카테고리의 parent_id를 업데이트합니다.
            update_sql = "UPDATE category SET parent_id = %s WHERE category_id = %s AND (parent_id IS NULL OR parent_id != %s)"
            cursor.execute(update_sql, (parent_id, child_id, parent_id))
            
            if cursor.rowcount > 0:
                print(f"  관계 설정: '{child_name}' (ID: {child_id})의 상위 ID를 '{parent_name}' (ID: {parent_id})로 업데이트.")

        # 최종 커밋
        conn.commit()
        print("\n--- 카테고리 계층 구조 삽입 및 관계 설정 완료 ---")
        
    except mysql.connector.Error as err:
        print(f"데이터베이스 오류 발생: {err}")
        if conn:
            conn.rollback()
            
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("MySQL 연결이 닫혔습니다.")

# --- 2단계: file 테이블 삽입 함수 (수정됨) ---

def insert_file_records(config, file_data):
    """
    로드된 파일-카테고리 데이터를 file 테이블의 새 구조에 맞게 삽입합니다.
    file_id는 순차적 숫자로, doc_id는 original_path 값으로 채웁니다.
    """
    if not file_data:
        print("삽입할 파일 데이터가 없습니다. 작업을 종료합니다.")
        return

    conn = None
    cursor = None
    category_id_map = {}
    
    # file_id는 Primary Key이며 순차적 숫자를 사용합니다.
    file_id_counter = 1 

    try:
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()
        
        print("\n--- 파일 레코드 삽입 시작 (새 구조 적용) ---")
        
        # 1. 현재 file 테이블의 최대 file_id를 조회하여 카운터 초기화
        cursor.execute("SELECT MAX(file_id) FROM file")
        max_file_id = cursor.fetchone()[0]
        if max_file_id is not None:
            file_id_counter = max_file_id + 1
        
        print(f"File ID 카운터를 {file_id_counter}부터 시작합니다.")

        # 2. 모든 카테고리 이름의 ID를 미리 조회 (성능 최적화)
        unique_categories = {item[0] for item in file_data}
        
        print(f"총 {len(unique_categories)}개의 고유 카테고리 ID 조회 중...")
        for name in unique_categories:
            cursor.execute("SELECT category_id FROM category WHERE category_name = %s", (name,))
            result = cursor.fetchone()
            
            if result:
                category_id_map[name] = result[0]
            else:
                print(f"경고: 카테고리 '{name}'에 대한 ID를 찾을 수 없습니다. 관련 파일은 건너뜁니다.")

        # 3. 파일 레코드 삽입
        for category_name, absolute_path in file_data:
            category_id = category_id_map.get(category_name)
            
            if category_id is None or not absolute_path:
                continue 
            
            # --- 새로운 필드 값 정의 ---
            current_file_id = file_id_counter
            doc_id = absolute_path         # 요청: doc_id는 original_path와 동일한 값을 사용
            original_path = absolute_path
            file_name = os.path.basename(absolute_path)
            
            # 파일 삽입 SQL (file_id, doc_id, original_path, file_name, category_id 순서)
            insert_sql = """
                INSERT INTO file (file_id, doc_id, original_path, file_name, category_id) 
                VALUES (%s, %s, %s, %s, %s)
            """
            
            try:
                # 5개 컬럼에 데이터 삽입
                cursor.execute(insert_sql, (current_file_id, doc_id, original_path, file_name, category_id))
                print(f"  파일 삽입: File_ID={current_file_id}, Doc_ID='{doc_id}', Cat_ID={category_id}")
                file_id_counter += 1
            except mysql.connector.Error as err:
                print(f"  오류: 파일 '{file_name}' 삽입 실패 (File_ID: {current_file_id}, SQL 오류): {err.msg}")
                # Primary Key(file_id) 또는 Unique Key(doc_id) 충돌 시 오류 발생 가능
                file_id_counter += 1 

        # 최종 커밋
        conn.commit()
        print("\n--- 파일 레코드 삽입 및 변경사항 커밋 완료 ---")
        
    except mysql.connector.Error as err:
        print(f"데이터베이스 오류 발생: {err}")
        if conn:
            conn.rollback()
            
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("MySQL 연결이 닫혔습니다.")

def category():
    # 1단계: category 테이블 데이터 삽입
    hierarchy_data = load_json_data(HIERARCHY_JSON_NAME)
    if hierarchy_data:
        insert_hierarchy_categories_from_file(DB_CONFIG, hierarchy_data)
        
    # 2단계: file 테이블 데이터 삽입
    file_data = load_json_data(FILE_CLUSTER_JSON_NAME)
    
    if file_data:
        insert_file_records(DB_CONFIG, file_data)
        
    print("\n--- 모든 데이터베이스 작업 완료 ---")