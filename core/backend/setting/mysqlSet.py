import mysql.connector
from mysql.connector import errorcode

from core.config import MYSQL_DB, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER

# 데이터베이스 연결 정보 설정 (사용자 환경에 맞게 수정 필요)
DB_CONFIG = {
    "user": MYSQL_USER,          # MySQL 사용자 이름으로 변경
    "password": MYSQL_PASSWORD,  # MySQL 비밀번호로 변경
    "host": MYSQL_HOST,
    "database": MYSQL_DB    # 사용할 데이터베이스 이름으로 변경
}

def create_tables(config):
    """
    MySQL 데이터베이스에 연결하고 'file'과 'category' 테이블을 생성합니다.
    (기존 테이블이 있으면 외래 키 순서에 맞게 삭제 후 다시 생성합니다.)
    """
    conn = None
    cursor = None
    
    # 1. 외래 키 제약 조건을 고려한 DROP 및 CREATE 문 정의
    # DROP 순서: 참조하는 file -> 참조되는 category
    DROP_TABLES = [
        "file",
        "category"
    ]
    
    # CREATE 순서: 참조되는 category -> 참조하는 file
    TABLES = {}
    
    # 3. category 테이블 생성 정의 (자기 참조 외래 키 포함)
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
    
    # 4. file 테이블 생성 정의 (category 테이블 참조 외래 키 포함)
    TABLES['file'] = (
        """
        CREATE TABLE file (
            file_id INT PRIMARY KEY,
            doc_id VARCHAR(512) NOT NULL,
            original_path VARCHAR(512) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            category_id INT UNSIGNED NOT NULL,
            FOREIGN KEY (category_id) REFERENCES category(category_id)
        )
        """
    )

    try:
        # 데이터베이스 연결
        print("MySQL 데이터베이스 연결 중...")
        conn = mysql.connector.connect(**config)
        cursor = conn.cursor()

        # --- 테이블 삭제 (DROP) ---
        for table_name in DROP_TABLES:
            try:
                print(f"테이블 '{table_name}' 삭제 시도...")
                # CASCADE를 사용하여 외래 키 제약 조건 무시하고 테이블 삭제
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                print(f"테이블 '{table_name}' 삭제 완료 또는 존재하지 않음.")
            except mysql.connector.Error as err:
                print(f"테이블 삭제 중 오류 발생 ({table_name}): {err.msg}")

        # --- 테이블 생성 (CREATE) ---
        for table_name, table_sql in TABLES.items():
            try:
                print(f"테이블 '{table_name}' 생성 시도...")
                cursor.execute(table_sql)
                print(f"테이블 '{table_name}' 성공적으로 생성됨.")
            except mysql.connector.Error as err:
                # 테이블이 이미 존재하는 경우 (CREATE IF NOT EXISTS 사용하지 않음)
                if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                    print(f"경고: 테이블 '{table_name}'이 이미 존재합니다.")
                else:
                    print(f"테이블 생성 중 오류 발생 ({table_name}): {err.msg}")

        # 변경사항 최종 커밋
        conn.commit()
        print("\n모든 테이블 생성 및 변경사항 커밋 완료.")

    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("오류: 사용자 이름 또는 비밀번호가 잘못되었습니다.")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print("오류: 데이터베이스가 존재하지 않습니다.")
        else:
            print(f"데이터베이스 연결 또는 작업 중 오류 발생: {err}")
            
    finally:
        # 연결 종료
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
            print("MySQL 연결이 닫혔습니다.")

# --- 함수 실행 ---
if __name__ == "__main__":
    # 실제 환경에 맞게 DB_CONFIG을 수정한 후 실행하세요.
    create_tables(DB_CONFIG)