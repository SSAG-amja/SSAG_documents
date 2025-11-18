# core/clustering.py
from typing import List, Dict, Tuple
import numpy as np

import hdbscan
from sklearn.preprocessing import normalize

from .types import DocChunk


def cluster_embeddings(
    embeddings: np.ndarray,
    chunks: List[DocChunk],
    min_cluster_size: int = 5,
    min_samples: int | None = None,
    use_cosine: bool = True,
    allow_noise: bool = True,
) -> Dict[int, List[DocChunk]]:
    """
    HDBSCAN으로 비지도 클러스터링.

    Parameters
    ----------
    embeddings : np.ndarray
        shape (N, D) 임베딩 벡터.
    chunks : List[DocChunk]
        길이 N, embeddings와 1:1 대응하는 청크 메타데이터.
    min_cluster_size : int
        최소 클러스터 크기. (너무 작으면 쪼개지고, 크면 합쳐짐)
    min_samples : int | None
        밀도 추정에 사용하는 최소 샘플 수.
        None이면 HDBSCAN이 min_cluster_size 기반으로 자동 설정.
    use_cosine : bool
        True면 코사인 유사도 기반으로 클러스터링 (L2 정규화 후 유클리드 거리).
    allow_noise : bool
        True면 label = -1 (노이즈)도 별도 클러스터로 유지.
        False면 노이즈 포인트들은 전부 버림.

    Returns
    -------
    Dict[int, List[DocChunk]]
        cluster_id -> DocChunk 리스트
        (노이즈는 allow_noise=True인 경우 cluster_id = -1로 들어감)
    """
    if len(chunks) == 0 or embeddings.shape[0] == 0:
        print("클러스터링할 데이터가 없습니다.")
        return {}

    if embeddings.shape[0] != len(chunks):
        raise ValueError("embeddings 개수와 chunks 개수가 다릅니다.")

    # 코사인 기반으로 보고 싶으면 L2 정규화 후 유클리드 거리 사용
    if use_cosine:
        X = normalize(embeddings)  # 각 벡터 길이를 1로 맞춤
        metric = "euclidean"
    else:
        X = embeddings
        metric = "euclidean"  # 필요하면 여기서 다른 metric으로 바꿔도 됨

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric=metric,
        # cluster_selection_epsilon=0.0  # 필요하면 튜닝 가능
    )

    labels = clusterer.fit_predict(X)  # shape (N,)

    clusters: Dict[int, List[DocChunk]] = {}
    for label, chunk in zip(labels, chunks):
        label_int = int(label)
        if label_int == -1 and not allow_noise:
            # 노이즈는 버린다
            continue
        clusters.setdefault(label_int, []).append(chunk)

    # 디버깅용 출력
    unique_labels = sorted(set(int(l) for l in labels))
    print(f"[HDBSCAN] 라벨 종류: {unique_labels}")
    print(f"[HDBSCAN] 클러스터 개수 (노이즈 포함 여부={allow_noise}): {len(clusters)}")

    return clusters


def build_virtual_tree_from_clusters(
    clusters: Dict[int, List[DocChunk]],
    include_noise_label: bool = True,
) -> Dict[str, List[str]]:
    """
    HDBSCAN 클러스터 결과를 '가상 디렉토리 트리' 형태로 단순 변환.

    - 현재는 cluster_0, cluster_1 ... 로 이름을 붙이고,
      각 클러스터 안에 속한 파일들의 file_path를 모아주는 역할.
    - label == -1 (노이즈)는 기본적으로 "noise" 키로 묶음.

    Returns
    -------
    Dict[str, List[str]]
        예시:
        {
            "cluster_0": ["C:/.../os_lecture1.pdf", ...],
            "cluster_1": ["C:/.../db_hw1.docx", ...],
            "noise":     ["C:/.../random.png", ...]  # 옵션
        }
    """
    virtual_tree: Dict[str, List[str]] = {}

    for cluster_id, chunk_list in clusters.items():
        if cluster_id == -1:
            if not include_noise_label:
                continue
            key = "noise"
        else:
            key = f"cluster_{cluster_id}"

        # 같은 파일이 여러 청크로 들어올 수 있으니 file_path는 unique로
        file_paths = sorted({c.file_path for c in chunk_list})
        virtual_tree[key] = file_paths

    return virtual_tree


def summarize_cluster_stats(
    clusters: Dict[int, List[DocChunk]]
) -> List[Tuple[int, int, int]]:
    """
    디버깅/로그용: 클러스터별 통계 정보 반환.

    Returns
    -------
    List[Tuple[int, int, int]]
        (cluster_id, 청크 개수, 고유 파일 수)
    """
    stats: List[Tuple[int, int, int]] = []

    for cid, chunk_list in clusters.items():
        num_chunks = len(chunk_list)
        unique_files = len({c.file_path for c in chunk_list})
        stats.append((cid, num_chunks, unique_files))

    # cluster_id 기준 정렬
    stats.sort(key=lambda x: x[0])
    return stats
