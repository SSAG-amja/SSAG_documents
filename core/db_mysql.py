# core/db_mysql.py
import os
from typing import Optional, Dict, List
import mysql.connector
from mysql.connector import MySQLConnection

from .config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DB
)
from .types import DocChunk

def get_connection() -> MySQLConnection:
    """MySQL 연결 객체 생성"""
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
    )
    return conn

def upsert_category(
    conn: MySQLConnection,
    category_name: str,
    parent_id: Optional[int] = None,
) -> int:
    """
    (category_name, parent_id) 조합이 있으면 기존 category_id 반환,
    없으면 새로 INSERT 후 category_id 반환.
    """
    cursor = conn.cursor()

    # 1) 기존 존재 확인 (테이블: category)
    select_sql = """
        SELECT category_id
        FROM category
        WHERE category_name = %s AND
              ((parent_id IS NULL AND %s IS NULL) OR parent_id = %s)
        LIMIT 1
    """
    cursor.execute(select_sql, (category_name, parent_id, parent_id))
    row = cursor.fetchone()

    if row:
        cat_id = row[0]
        cursor.close()
        return cat_id

    # 2) 없으면 새로 INSERT
    insert_sql = """
        INSERT INTO category (category_name, parent_id)
        VALUES (%s, %s)
    """
    cursor.execute(insert_sql, (category_name, parent_id))
    conn.commit()

    cat_id = cursor.lastrowid
    cursor.close()
    return cat_id

def insert_file_if_not_exists(
    conn: MySQLConnection,
    doc_id: str,        # 절대 경로 (PK)
    file_name: str,
    category_id: int,
) -> str:
    """
    file 테이블 스키마 반영:
    - doc_id (PK, VARCHAR)
    - original_path (doc_id와 동일하게 저장)
    - file_name
    - category_id
    """
    cursor = conn.cursor()

    # 1) PK(doc_id)로 존재 여부 확인 (테이블: file)
    select_sql = "SELECT doc_id FROM file WHERE doc_id = %s LIMIT 1"
    cursor.execute(select_sql, (doc_id,))
    row = cursor.fetchone()

    if row:
        # 이미 존재하면 아무것도 안 하고 ID 반환
        cursor.close()
        return row[0]

    # 2) INSERT (original_path는 doc_id와 동일하게 처리)
    insert_sql = """
        INSERT INTO file (doc_id, original_path, file_name, category_id)
        VALUES (%s, %s, %s, %s)
    """
    cursor.execute(insert_sql, (doc_id, doc_id, file_name, category_id))
    conn.commit()

    cursor.close()
    return doc_id

def save_clusters_to_db_flat(
    conn: MySQLConnection,
    clusters: Dict[int, List[DocChunk]],
    cluster_labels: Dict[int, Dict[str, str]],
    root_category_name: str = "AI Virtual Directory",
) -> None:
    """
    클러스터링 결과를 DB에 저장하는 로직.
    변경된 테이블(category, file) 구조에 맞춰 수정됨.
    """
    # 1) 루트 카테고리 생성
    root_id = upsert_category(conn, root_category_name, parent_id=None)

    for cid, chunk_list in clusters.items():
        label_info = cluster_labels.get(cid, {})
        raw_label = label_info.get("label", f"cluster_{cid}")
        cluster_cat_name = raw_label.strip() or f"cluster_{cid}"

        # 2) 클러스터 카테고리 생성 (부모: root_id)
        cluster_cat_id = upsert_category(conn, cluster_cat_name, parent_id=root_id)

        # 3) 파일 저장 (doc_id 중복 방지)
        unique_files = {}
        for ch in chunk_list:
            # ch.file_path 가 doc_id 역할
            if ch.file_path not in unique_files:
                unique_files[ch.file_path] = ch

        for path, ch in unique_files.items():
            file_name = os.path.basename(path)
            insert_file_if_not_exists(
                conn,
                doc_id=path,          # 절대 경로를 doc_id로 사용
                file_name=file_name,
                category_id=cluster_cat_id,
            )

    print("✅ 클러스터 결과를 MySQL category/file 테이블에 저장 완료.")

def clear_all_data(conn: MySQLConnection):
    """
    DB의 모든 카테고리와 파일 데이터를 삭제합니다 (초기화).
    """
    cursor = conn.cursor()
    try:
        # 외래 키 제약 조건을 잠시 끄고 삭제 (순서 상관없이 지우기 위해)
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute("TRUNCATE TABLE file;")
        cursor.execute("TRUNCATE TABLE category;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        conn.commit()
        print("🗑️ DB 데이터 전체 삭제 완료.")
    except Exception as e:
        print(f"DB 삭제 중 오류: {e}")
    finally:
        cursor.close()