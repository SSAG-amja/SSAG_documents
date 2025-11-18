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
    """
    MySQL 연결 객체 생성.
    """
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
    name: str,
    parent_id: Optional[int] = None,
) -> int:
    """
    (name, parent_id) 조합이 이미 있으면 그 id를 반환,
    없으면 새로 INSERT 후 id 반환.
    """
    cursor = conn.cursor()

    # 1) 기존 있는지 확인
    select_sql = """
        SELECT id
        FROM category
        WHERE name = %s AND
              ((parent_id IS NULL AND %s IS NULL) OR parent_id = %s)
        LIMIT 1
    """
    cursor.execute(select_sql, (name, parent_id, parent_id))
    row = cursor.fetchone()

    if row:
        category_id = row[0]
        cursor.close()
        return category_id

    # 2) 없으면 새로 INSERT
    insert_sql = """
        INSERT INTO category (name, parent_id)
        VALUES (%s, %s)
    """
    cursor.execute(insert_sql, (name, parent_id))
    conn.commit()

    category_id = cursor.lastrowid
    cursor.close()
    return category_id


def insert_file_if_not_exists(
    conn: MySQLConnection,
    file_name: str,
    file_path: str,
    category_id: int,
) -> int:
    """
    file_path 기준으로 이미 존재하면 기존 id를 반환하고,
    없으면 새로 INSERT 후 id 반환.
    """
    cursor = conn.cursor()

    select_sql = """
        SELECT id FROM file
        WHERE file_path = %s
        LIMIT 1
    """
    cursor.execute(select_sql, (file_path,))
    row = cursor.fetchone()

    if row:
        file_id = row[0]
        cursor.close()
        return file_id

    insert_sql = """
        INSERT INTO file (file_name, file_path, category_id)
        VALUES (%s, %s, %s)
    """
    cursor.execute(insert_sql, (file_name, file_path, category_id))
    conn.commit()

    file_id = cursor.lastrowid
    cursor.close()
    return file_id


def save_clusters_to_db_flat(
    conn: MySQLConnection,
    clusters: Dict[int, List[DocChunk]],
    cluster_labels: Dict[int, Dict[str, str]],
    root_category_name: str = "AI Virtual Directory",
) -> None:
    """
    [전제]
      - HDBSCAN 결과: clusters = {cluster_id: [DocChunk, ...], ...}
      - Solar 라벨링 결과: cluster_labels = {
            cid: {"label": "...", "description": "..."},
        }

    [동작]
      1) root 카테고리 하나 생성 (ex: "AI Virtual Directory")
      2) 각 cluster_id 에 대해:
         - cluster_labels[cid]["label"] 이름으로 하위 카테고리 생성
         - 그 카테고리에 해당 클러스터 안의 파일들을 매핑하여 file 테이블 INSERT

    [주의]
      - 파일은 file_path 기준으로 unique 처리 (같은 파일 여러 청크 → file 한 줄만).
    """
    # 1) 루트 카테고리 생성 / 재사용
    root_id = upsert_category(conn, root_category_name, parent_id=None)

    for cid, chunk_list in clusters.items():
        label_info = cluster_labels.get(cid, {})
        raw_label = label_info.get("label", f"cluster_{cid}")

        # label이 너무 길거나 공백 많으면 적당히 다듬어도 됨
        cluster_cat_name = raw_label.strip() or f"cluster_{cid}"

        # 2) 클러스터용 카테고리 생성 (부모: root_id)
        cluster_cat_id = upsert_category(conn, cluster_cat_name, parent_id=root_id)

        # 3) 이 클러스터에 속한 파일들을 file 테이블에 저장
        #    - DocChunk는 청크 단위라서, file_path 기준으로 먼저 unique 처리
        unique_paths = {}
        for ch in chunk_list:
            # 같은 path면 나중 청크는 무시 (어차피 파일 한 줄만 필요)
            if ch.file_path not in unique_paths:
                unique_paths[ch.file_path] = ch

        for path, ch in unique_paths.items():
            # 파일 이름만 추출 (경로에서 마지막 부분)
            file_name = os.path.basename(path)
            insert_file_if_not_exists(
                conn,
                file_name=file_name,
                file_path=path,
                category_id=cluster_cat_id,
            )

    print("✅ 클러스터 결과를 MySQL category/file 테이블에 저장 완료.")
