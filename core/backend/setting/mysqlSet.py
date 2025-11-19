# core/backend/setting/mysqlSet.py

import os
import mysql.connector
from mysql.connector import errorcode, MySQLConnection
from typing import Optional, Dict, List

# 상위 폴더의 설정값과 타입 가져오기
from core.config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB
)
from core.types import DocChunk

# ---------------------------------------------------------
# 1. 연결(Connection) 설정
# ---------------------------------------------------------
def get_connection() -> MySQLConnection:
    """MySQL 연결 객체 생성 (중앙 집중식 관리)"""
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
    )
    return conn

# ---------------------------------------------------------
# 2. 테이블 생성 및 초기화 (Schema)
# ---------------------------------------------------------
def create_tables():
    """
    DB 테이블이 없으면 생성하고, 초기화가 필요할 때 호출합니다.
    app.py나 스캔 시작 시 호출됩니다.
    """
    conn = None
    cursor = None
    
    # 외래 키 순서 고려: 자식(file) -> 부모(category) 순 삭제
    DROP_TABLES = ["file", "category"]
    
    # 생성 순서: 부모(category) -> 자식(file)
    TABLES = {}
    TABLES['category'] = (
        """
        CREATE TABLE category (
            category_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            category_name VARCHAR(255) NOT NULL,
            parent_id INT UNSIGNED NULL,
            PRIMARY KEY (category_id),
            FOREIGN KEY (parent_id) REFERENCES category(category_id)
        )
        """
    )
    TABLES['file'] = (
        """
        CREATE TABLE file (
            file_id INT NOT NULL AUTO_INCREMENT,
            doc_id VARCHAR(512) NOT NULL,
            original_path VARCHAR(512) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            category_id INT UNSIGNED NOT NULL,
            PRIMARY KEY (file_id),
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
        """
    )

    try:
        print("MySQL 데이터베이스 연결 및 테이블 점검 중...")
        conn = get_connection()
        cursor = conn.cursor()

        # 1) 기존 테이블 삭제 (Reset 로직이 필요할 때만 유효, 평소엔 주석 처리 가능하지만 현재 구조상 유지)
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;") 
        for table_name in DROP_TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        # 2) 테이블 생성
        for table_name, table_sql in TABLES.items():
            try:
                cursor.execute(table_sql)
                print(f"✅ 테이블 '{table_name}' 생성 완료.")
            except mysql.connector.Error as err:
                if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                    print(f"⚠️ 테이블 '{table_name}'이 이미 존재합니다.")
                else:
                    print(f"❌ 테이블 생성 오류 ({table_name}): {err.msg}")

        conn.commit()
        print("🏁 DB 테이블 세팅 완료.")

    except mysql.connector.Error as err:
        print(f"DB 연결/작업 오류: {err}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def clear_all_data():
    """
    테이블 구조는 남기고 데이터만 삭제 (TRUNCATE)
    UI의 '화면 초기화' 버튼에서 사용
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute("TRUNCATE TABLE file;")
        cursor.execute("TRUNCATE TABLE category;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        conn.commit()
        print("🗑️ DB 데이터 전체 삭제 완료 (Truncate).")
    except Exception as e:
        print(f"DB 삭제 중 오류: {e}")
    finally:
        cursor.close()
        conn.close()

# ---------------------------------------------------------
# 3. 데이터 조작 (CRUD Helpers)
# ---------------------------------------------------------
def upsert_category(conn: MySQLConnection, category_name: str, parent_id: Optional[int] = None) -> int:
    cursor = conn.cursor()
    # 조회
    select_sql = """
        SELECT category_id FROM category
        WHERE category_name = %s AND ((parent_id IS NULL AND %s IS NULL) OR parent_id = %s)
        LIMIT 1
    """
    cursor.execute(select_sql, (category_name, parent_id, parent_id))
    row = cursor.fetchone()
    
    if row:
        cursor.close()
        return row[0]

    # 삽입
    insert_sql = "INSERT INTO category (category_name, parent_id) VALUES (%s, %s)"
    cursor.execute(insert_sql, (category_name, parent_id))
    conn.commit()
    
    cat_id = cursor.lastrowid
    cursor.close()
    return cat_id

def insert_file_if_not_exists(conn: MySQLConnection, doc_id: str, file_name: str, category_id: int) -> str:
    cursor = conn.cursor()
    # 조회
    select_sql = "SELECT doc_id FROM file WHERE doc_id = %s LIMIT 1"
    cursor.execute(select_sql, (doc_id,))
    row = cursor.fetchone()
    
    if row:
        cursor.close()
        return row[0]

    # 삽입
    insert_sql = """
        INSERT INTO file (doc_id, original_path, file_name, category_id)
        VALUES (%s, %s, %s, %s)
    """
    cursor.execute(insert_sql, (doc_id, doc_id, file_name, category_id))
    conn.commit()
    
    cursor.close()
    return doc_id

# ---------------------------------------------------------
# 4. 클러스터링 결과 저장 (메인 로직)
# ---------------------------------------------------------
def save_clusters_to_db_flat(
    clusters: Dict[int, List[DocChunk]],
    cluster_labels: Dict[int, Dict[str, str]],
    root_category_name: str = "AI Virtual Directory",
) -> None:
    """
    클러스터링 결과를 DB에 저장합니다.
    외부에서 호출 시 이 함수만 쓰면 됩니다.
    """
    print("💾 클러스터링 결과 DB 저장 시작...")
    conn = get_connection()
    
    try:
        # 1) 루트 카테고리 생성
        root_id = upsert_category(conn, root_category_name, parent_id=None)

        for cid, chunk_list in clusters.items():
            # 라벨 결정
            label_info = cluster_labels.get(cid, {})
            raw_label = label_info.get("label", f"cluster_{cid}")
            cluster_cat_name = raw_label.strip() or f"cluster_{cid}"

            # 2) 클러스터 카테고리 생성
            cluster_cat_id = upsert_category(conn, cluster_cat_name, parent_id=root_id)

            # 3) 파일 저장 (중복 경로 제거)
            unique_files = {}
            for ch in chunk_list:
                if ch.file_path not in unique_files:
                    unique_files[ch.file_path] = ch

            for path, ch in unique_files.items():
                file_name = os.path.basename(path)
                insert_file_if_not_exists(
                    conn,
                    doc_id=path, # 절대 경로를 ID로 사용
                    file_name=file_name,
                    category_id=cluster_cat_id,
                )
        print("✅ DB 저장 완료.")
        
    except Exception as e:
        print(f"❌ DB 저장 실패: {e}")
    finally:
        if conn.is_connected():
            conn.close()