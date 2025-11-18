from dataclasses import dataclass

@dataclass
class DocChunk:
    id: str
    file_path: str
    chunk_index: int
    text: str
