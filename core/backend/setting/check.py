"""패키지 확인 코드 - 구버전"""

import sys
from pathlib import Path
from core.config import QDRANT_API_KEY, QDRANT_URL, MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER

print("=== Python & pip 확인 ===")
print("Python 버전:", sys.version)
try:
    import pip
    print("pip 버전:", pip.__version__)
except ImportError:
    print("pip가 설치되어 있지 않습니다.")

# -------------------------------
print("\n=== 패키지 설치 확인 ===")
# 패키지와 import 이름 매핑
packages = {
    "pandas": "pandas",
    "python-magic": "magic",
    "python-docx": "docx",
    "PyPDF2": "PyPDF2",
    "pdfplumber": "pdfplumber",
    "pytesseract": "pytesseract",
    "nltk": "nltk",
    "regex": "regex",
    "qdrant-client": "qdrant_client",
    "requests": "requests",
    "mysql-connector-python": "mysql.connector"
}

for pkg_name, import_name in packages.items():
    try:
        __import__(import_name)
        print(f"[OK] {pkg_name} 설치됨")
    except ImportError:
        print(f"[X] {pkg_name} 설치 필요")

# -------------------------------
print("\n=== MySQL 연결 테스트 ===")
try:
    import mysql.connector
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB
    )
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES;")
    print("MySQL 연결 성공, 테이블:", cursor.fetchall())
    conn.close()
except Exception as e:
    print("MySQL 연결 실패:", e)

# -------------------------------
print("\n=== Qdrant 연결 테스트 ===")
try:
    from qdrant_client import QdrantClient
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY  # 실제 API 키로 변경
    )
    collections = client.get_collections()
    print("Qdrant 연결 성공, 컬렉션:", collections)
except Exception as e:
    print("Qdrant 연결 실패:", e)

# -------------------------------
print("\n=== 디렉토리 접근 테스트 ===")
try:
    target_dir = Path("/Users/gimhoyeong/Desktop")
    files = list(target_dir.rglob("*"))
    print(f"타겟 디렉토리 파일 개수: {len(files)}")
    print("예시 파일:", files[:5])
except Exception as e:
    print("디렉토리 접근 실패:", e)
