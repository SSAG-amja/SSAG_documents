# core/tree_loader.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from .db_mysql import get_connection


@dataclass
class FileEntry:
    id: int
    name: str
    path: str


@dataclass
class CategoryNode:
    id: int
    name: str
    parent_id: Optional[int]
    children: List["CategoryNode"] = field(default_factory=list)
    files: List[FileEntry] = field(default_factory=list)


def load_virtual_tree_from_db() -> List[CategoryNode]:
    """
    MySQL의 category, file 테이블을 읽어서
    루트 카테고리 리스트(트리 구조)를 반환.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 1) category 모두 읽기
    cursor.execute("SELECT id, name, parent_id FROM category")
    rows = cursor.fetchall()

    nodes: Dict[int, CategoryNode] = {}
    for cid, name, parent_id in rows:
        nodes[cid] = CategoryNode(
            id=cid,
            name=name,
            parent_id=parent_id,
        )

    # 2) 부모-자식 연결
    roots: List[CategoryNode] = []
    for cid, node in nodes.items():
        if node.parent_id is None:
            roots.append(node)
        else:
            parent = nodes.get(node.parent_id)
            if parent:
                parent.children.append(node)
            else:
                # parent_id가 있는데 부모가 없으면 그냥 루트로 취급 (예외 케이스)
                roots.append(node)

    # 3) file 테이블 읽어서 각 카테고리에 붙이기
    cursor.execute("SELECT id, file_name, file_path, category_id FROM file")
    file_rows = cursor.fetchall()

    for fid, fname, fpath, category_id in file_rows:
        cat_node = nodes.get(category_id)
        if not cat_node:
            continue
        cat_node.files.append(
            FileEntry(
                id=fid,
                name=fname,
                path=fpath,
            )
        )

    cursor.close()
    conn.close()

    # 자식 카테고리/파일 정렬(보기 좋게)
    def sort_tree(node: CategoryNode):
        node.children.sort(key=lambda c: c.name.lower())
        node.files.sort(key=lambda f: f.name.lower())
        for child in node.children:
            sort_tree(child)

    for root in roots:
        sort_tree(root)

    return roots
