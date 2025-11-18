# app.py (v5. UI 고정 및 절대경로 완벽 적용)
import sys
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
import time, random, string

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel, 
    QListWidget, QListWidgetItem, QFileDialog, 
    QSplitter, QLineEdit, QGroupBox, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtCore import Qt
from core.db_mysql import get_connection, clear_all_data
from core.tree_loader import load_virtual_tree_from_db

from openai import OpenAI
from core.config import UPSTAGE_API_KEY

# -------------------------------------------------------------------
# 데이터 클래스
# -------------------------------------------------------------------
@dataclass
class RootItem:
    id: str
    name: str
    tree: list = field(default_factory=list) 
    total_files: int = 0

# -------------------------------------------------------------------
# 메인 윈도우
# -------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("문서 임베딩 / 가상 디렉토리 GUI (v5 - UI 고정)")
        self.resize(1200, 750)
        self.current_root: RootItem | None = None

        # [UI 수정 1] 하단 상태바 생성 (상단 라벨 제거하여 UI 밀림 방지)
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("준비 완료")

        # ================= 중앙 전체 레이아웃 =================
        central = QWidget()
        central_layout = QVBoxLayout(central)
        # 상단 여백 최소화
        central_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)
        
        # ---------------------------
        # [왼쪽] 기능 패널
        # ---------------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 디렉토리 그룹
        scan_group = QGroupBox("디렉토리")
        scan_layout = QVBoxLayout(scan_group)
        
        self.btn_scan = QPushButton("📁 디렉토리 스캔")
        self.btn_scan.clicked.connect(self.handle_scan_click)
        
        self.btn_clean = QPushButton("🧹 화면 초기화")
        self.btn_clean.clicked.connect(self.handle_clean_click)
        
        # [UI 수정 2] 버튼 글씨를 바꾸지 않고, 별도 라벨에 정보를 표시 (UI 고정)
        self.lbl_current_dir = QLabel("선택된 폴더 없음")
        self.lbl_current_dir.setStyleSheet("color: gray; font-size: 11px;")
        self.lbl_current_dir.setWordWrap(True) # 경로가 길면 줄바꿈

        scan_layout.addWidget(self.btn_scan)
        scan_layout.addWidget(self.lbl_current_dir) # 정보 라벨 추가
        scan_layout.addWidget(self.btn_clean)
        
        left_layout.addWidget(scan_group)

        # 2. 검색 그룹
        search_group = QGroupBox("검색")
        search_layout = QVBoxLayout(search_group)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("키워드 검색")
        self.btn_search = QPushButton("검색")
        self.btn_search.clicked.connect(self.handle_search_click)
        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.handle_search_file_open)
        
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_search)
        search_layout.addWidget(self.search_results_list)
        
        left_layout.addWidget(search_group, stretch=1)

        # 3. 추가 기능 섹션
        extra_group = QGroupBox("추가 기능")
        extra_layout = QVBoxLayout(extra_group)
        self.btn_summary = QPushButton("요약 생성 (TODO)")
        self.btn_report = QPushButton("보고서 제작 (TODO)")
        self.btn_summary.clicked.connect(self.handle_summary_clicked)
        self.btn_report.clicked.connect(self.handle_report_clicked)
        extra_layout.addWidget(self.btn_summary)
        extra_layout.addWidget(self.btn_report)
        
        left_layout.addWidget(extra_group)

        # ---------------------------
        # [오른쪽] 트리 뷰 패널
        # ---------------------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.current_root_label = QLabel("현재 루트: (없음)")
        self.current_root_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(self.current_root_label)
        
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabel("가상 디렉토리 구조")
        self.file_tree.itemDoubleClicked.connect(self.handle_tree_file_open)
        right_layout.addWidget(self.file_tree)

        # 스플리터 설정
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 900])
        central_layout.addWidget(splitter)
        self.setCentralWidget(central)

    # ===============================================================
    # [핵심 기능 1] 디렉토리 스캔 (절대 경로 & 중복 제거)
    # ===============================================================
    def scan_directory_unique(self, dir_path: str) -> list[str]:
        """
        파일명 기준 중복 제거 + 무조건 절대 경로(Absolute Path) 반환
        """
        file_paths = []
        seen_filenames = set()
        
        # 입력된 경로 자체도 절대 경로로 변환하여 시작
        abs_root_path = os.path.abspath(dir_path)
        print(f"\n🚀 스캔 시작: {abs_root_path}")

        for root, dirs, files in os.walk(abs_root_path):
            for name in files:
                if name.startswith('.'): continue # 숨김 파일 제외
                
                if name in seen_filenames:
                    print(f"⚠️ [중복 제외] {name}")
                    continue
                
                seen_filenames.add(name)
                
                # [중요] 경로 결합 후 절대 경로로 변환하여 저장
                full_path = os.path.join(root, name)
                abs_path = os.path.abspath(full_path) 
                
                file_paths.append(abs_path)
                
        return file_paths

    def handle_scan_click(self):
        dir_path = QFileDialog.getExistingDirectory(self, "스캔할 폴더 선택", os.path.expanduser("~"))
        if not dir_path: return

        self.status_bar.showMessage(f"스캔 중... {dir_path}")
        
        try:
            # 1. 파일 스캔 (절대 경로 리스트 획득)
            unique_files = self.scan_directory_unique(dir_path)
            abs_path = os.path.abspath(dir_path)
            self.current_root_label.setText(f"현재 루트: {abs_path}")

            folder_name = Path(dir_path).name
            self.lbl_current_dir.setText(f"📂 {folder_name} ({len(unique_files)}개 파일)")
            self.status_bar.showMessage(f"스캔 완료: 총 {len(unique_files)}개 파일 대기 중")
            
            # TODO: 나중에 여기서 process_files_and_save(unique_files) 호출
        except Exception as e:
            self.status_bar.showMessage(f"오류 발생: {e}")
            print(e)

    # ===============================================================
    # [핵심 기능 2] 화면 및 DB 초기화
    # ===============================================================
    def handle_clean_click(self):
        try:
            # DB 삭제
            conn = get_connection()
            clear_all_data(conn)
            conn.close()
            
            # UI 초기화
            self.file_tree.clear()
            self.search_results_list.clear()
            self.search_input.clear()
            self.current_root = None
            
            # 라벨 초기화
            self.current_root_label.setText("현재 루트: (없음)")
            self.lbl_current_dir.setText("선택된 폴더 없음")
            self.status_bar.showMessage("초기화 완료. DB 및 화면이 정리되었습니다.")
            
            print("🧹 화면 및 DB 초기화 완료.")
            
        except Exception as e:
            print(f"초기화 실패: {e}")
            self.status_bar.showMessage(f"초기화 실패: {e}")

    # ===============================================================
    # [핵심 기능 3] DB -> UI 갱신 (재사용 가능한 함수) -> DB 저장작업 끝나면 호출만하면됨
    # ===============================================================
    def refresh_ui_from_db(self):
        """외부(AI 로직 등)에서 호출하여 화면을 갱신하는 함수"""
        print("🔄 DB에서 UI 갱신 시작...")
        try:
            db_roots = load_virtual_tree_from_db()
            self.file_tree.clear()
            
            if not db_roots:
                print("표시할 데이터가 없습니다.")
                self.status_bar.showMessage("DB 데이터 없음")
                return

            for root_node in db_roots:
                self.populate_tree(self.file_tree, root_node)
            
            self.status_bar.showMessage("가상 디렉토리 구조 로드 완료")
            self.current_root_label.setText("현재 루트: AI 가상 디렉토리")
            print("✅ UI 갱신 완료.")
            
        except Exception as e:
            print(f"UI 갱신 에러: {e}")
            self.status_bar.showMessage("UI 갱신 오류")

    def populate_tree(self, parent_widget, category_node):
        """트리 아이템 재귀 생성"""
        folder_item = QTreeWidgetItem(parent_widget)
        folder_item.setText(0, f"📂 {category_node.name}")
        folder_item.setExpanded(True)
        
        for file_entry in category_node.files:
            file_item = QTreeWidgetItem(folder_item)
            file_item.setText(0, f"📄 {file_entry.name}")
            # [중요] 절대 경로 저장 (더블클릭 열기용)
            file_item.setData(0, Qt.UserRole, file_entry.path)

        for child in category_node.children:
            self.populate_tree(folder_item, child)

    # ===============================================================
    # [기타 기능] 파일 열기 및 추가 기능 핸들러
    # ===============================================================
    def handle_tree_file_open(self, item, column):
        path = item.data(0, Qt.UserRole)
        if path: self.open_file(path)

    def handle_search_file_open(self, item):
        path = item.data(Qt.UserRole)
        if path: self.open_file(path)

    def open_file(self, path):
        # 저장된 경로가 절대경로인지 한번 더 확인 및 처리
        abs_path = os.path.abspath(path)
        
        if not os.path.exists(abs_path):
            self.status_bar.showMessage(f"파일을 찾을 수 없음: {abs_path}")
            return

        try:
            if platform.system() == "Windows": os.startfile(abs_path)
            elif platform.system() == "Darwin": 
                import subprocess
                subprocess.run(["open", abs_path], check=False)
            else: 
                import subprocess
                subprocess.run(["xdg-open", abs_path], check=False)
            print(f"파일 열기: {abs_path}")
            self.status_bar.showMessage(f"열기: {os.path.basename(abs_path)}")
        except Exception as e:
            print(f"열기 실패: {e}")
            self.status_bar.showMessage(f"열기 실패: {e}")

    def handle_search_click(self):
        # 1. 검색어 가져오기'
        self.search_input.clearFocus()
        query_text = self.search_input.text().strip()
        if not query_text:
            self.status_bar.showMessage("검색어를 입력하세요.")
            return

        self.status_bar.showMessage(f"Solar API 호출 중... '{query_text}'")
        self.btn_search.setText("⏳ 임베딩 중...")
        self.btn_search.setEnabled(False)

        try:
            # -------------------------------------------------------
            # (A) Solar (Upstage) API로 텍스트 -> 벡터 변환
            # -------------------------------------------------------
            client = OpenAI(
                api_key=UPSTAGE_API_KEY,
                base_url="https://api.upstage.ai/v1"
            )
            
            # Solar 임베딩 모델 호출
            response = client.embeddings.create(
                input=query_text,
                model="embedding-query" 
            )
            
            # 결과 벡터 추출 (이게 핵심 데이터!)
            query_vector = response.data[0].embedding
            
            # -------------------------------------------------------
            # (B) 결과 확인 (Qdrant 팀원에게 넘겨줄 데이터)
            # -------------------------------------------------------
            vector_dim = len(query_vector) # 벡터 차원 (보통 4096)
            print(f"\n✅ [성공] '{query_text}' 임베딩 완료!")
            print(f"   - 벡터 차원수: {vector_dim}")
            print(f"   - 벡터 앞부분 5개: {query_vector[:5]} ...")
            
            # [TODO] 나중에 Qdrant 담당자가 구현할 함수에 이 query_vector를 넘기면 됨
            # 예: qdrant_module.search(query_vector)
            
            self.status_bar.showMessage(f"임베딩 성공! (차원: {vector_dim}) - 터미널 확인")
            
            # UI에 임시 결과 표시
            self.search_results_list.clear()

            # 이부분 반환되는 파일 올리면됨
            self.search_results_list.addItem(f"✅ 변환 성공 (길이: {vector_dim})")
            self.search_results_list.addItem(f"데이터: {query_vector[:5]}...")

        except Exception as e:
            print(f"Solar API 오류: {e}")
            self.status_bar.showMessage(f"API 오류: {e}")
            
        finally:
            self.btn_search.setText("검색")
            self.btn_search.setEnabled(True)

    def handle_summary_clicked(self):
        print("요약 생성 기능 (TODO)")

    def handle_report_clicked(self):
        print("보고서 제작 기능 (TODO)")

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()