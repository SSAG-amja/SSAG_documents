# core/types.py
from dataclasses import dataclass

@dataclass
class DocChunk:
    id: str          # 청크 고유 ID (file_path + index + uuid 등)
    file_path: str   # 원본 파일 절대 경로
    chunk_index: int # 해당 파일 내에서 청크 인덱스 (0, 1, 2, ...)
    text: str        # 이 청크의 실제 텍스트 내용


# 테스트용 임시