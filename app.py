# app.py (v3. 클린 기능 추가 및 스캔 로직 변경)
import sys
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
import time, random, string # uuid용

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem,
    QSplitter, QLineEdit,
    QGroupBox, QTreeWidget, QTreeWidgetItem
)
from PySide6.QtCore import Qt
from core.db_mysql import get_connection, clear_all_data  # clear_all_data 추가
from core.tree_loader import load_virtual_tree_from_db


# -------------------------------------------------------------------
# (데이터 클래스 - 변경 없음)
# -------------------------------------------------------------------
@dataclass
class RootItem:
    id: str
    name: str
    tree: dict = field(default_factory=dict)   # virtual directory tree
    total_files: int = 0


def uuid() -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + hex(int(time.time()))[2:]


# -------------------------------------------------------------------
# 메인 윈도우
# -------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("문서 임베딩 / 가상 디렉토리 GUI (v3)")
        self.resize(1200, 700)

        self.current_root: RootItem | None = None
        self.search_results: list[Path] = []
        self.is_loading: bool = False

        # ================= 중앙 전체 레이아웃 =================
        central = QWidget()
        central_layout = QVBoxLayout(central)

        self.status_label = QLabel("상태: 스캔할 디렉토리를 선택하세요.")
        central_layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ---------------------------
        # [왼쪽] 모든 기능 패널
        # ---------------------------
        left_panel_widget = QWidget()
        left_layout = QVBoxLayout(left_panel_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # ── [1] 디렉토리 스캔 ──────────────────────────
        scan_group = QGroupBox("디렉토리")
        scan_layout = QVBoxLayout(scan_group)

        self.btn_scan = QPushButton("📁 디렉토리 스캔")
        self.btn_scan.clicked.connect(self.handle_scan_click)
        scan_layout.addWidget(self.btn_scan)

        # [추가] 화면 초기화(Clean) 버튼 추가
        self.btn_clean = QPushButton("🧹 화면 초기화")
        self.btn_clean.clicked.connect(self.handle_clean_click)
        scan_layout.addWidget(self.btn_clean)

        left_layout.addWidget(scan_group)

        # ── [2] 검색 섹션 ──────────────
        search_group = QGroupBox("검색")
        search_layout = QVBoxLayout(search_group)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (파일명 기준, 임시)")
        btn_search = QPushButton("검색")
        btn_search.clicked.connect(self.handle_search_click)

        search_layout.addWidget(self.search_input)
        search_layout.addWidget(btn_search)

        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.handle_file_open)
        search_layout.addWidget(self.search_results_list, stretch=1)

        left_layout.addWidget(search_group, stretch=1)

        # ── [3] 추가 기능 섹션 ───────────
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
        # [오른쪽] 파일 리스트 -> 트리 위젯으로 변경
        # ---------------------------
        right_panel_widget = QWidget()
        right_layout = QVBoxLayout(right_panel_widget)

        self.current_root_label = QLabel("현재 루트: (없음)")
        right_layout.addWidget(self.current_root_label)

        # [수정] QListWidget -> QTreeWidget
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabel("가상 디렉토리 구조") # 헤더 이름 설정
        self.file_tree.itemDoubleClicked.connect(self.handle_file_open) # 더블클릭 연결
        right_layout.addWidget(self.file_tree, stretch=1)
        # ---------------------------
        # splitter 설정 (변경 없음)
        # ---------------------------
        splitter.addWidget(left_panel_widget)
        splitter.addWidget(right_panel_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3) 
        splitter.setSizes([300, 900]) 

        central_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        # [신규 추가] DB 트리 객체를 GUI용 딕셔너리로 변환
    def convert_nodes_to_dict(self, nodes) -> dict:
        result = {}
        
        # 재귀적으로 트리를 순회하며 "카테고리 -> 파일리스트" 형태로 만듭니다.
        def traverse(node, path_prefix=""):
            # 현재 카테고리 이름 (깊이가 있으면 "부모 > 자식" 형태로 표시)
            current_name = f"{path_prefix} > {node.name}" if path_prefix else node.name
            
            # 이 카테고리에 파일이 있으면 결과에 추가
            if node.files:
                # GUI는 파일 경로 문자열의 리스트를 원함
                file_paths = [f.path for f in node.files]
                result[current_name] = file_paths
            
            # 자식 카테고리들도 탐색
            for child in node.children:
                traverse(child, current_name)

        for root in nodes:
            traverse(root)
            
        return result
    
        # [신규 추가] 트리 위젯에 노드를 재귀적으로 추가하는 함수
    def populate_tree(self, parent_widget, category_node):
        """
        parent_widget: QTreeWidget 또는 QTreeWidgetItem
        category_node: CategoryNode 객체 (DB에서 가져온 것)
        """
        # 1. 현재 카테고리(폴더) 아이템 생성
        folder_item = QTreeWidgetItem(parent_widget)
        folder_item.setText(0, f"📂 {category_node.name}")
        folder_item.setExpanded(True) # 기본적으로 펼쳐두기 (싫으면 False)
        
        # 2. 해당 카테고리 안의 파일들 추가
        for file_entry in category_node.files:
            file_item = QTreeWidgetItem(folder_item)
            file_item.setText(0, f"📄 {file_entry.name}")
            # 파일 경로는 숨겨진 데이터로 저장 (더블클릭 시 열기 위함)
            file_item.setData(0, Qt.UserRole, file_entry.path)

        # 3. 자식 카테고리(하위 폴더)가 있으면 재귀 호출
        for child_node in category_node.children:
            self.populate_tree(folder_item, child_node)

    # -------------------------------------------------------------------
    # 1. 디렉토리 스캔 버튼
    # -------------------------------------------------------------------
    # [수정] handle_scan_click
    def handle_scan_click(self):
        self.set_loading(True)
        self.status_label.setText("상태: DB 로드 중...")
        
        try:
            # 1. DB에서 트리 구조 가져오기
            db_roots = load_virtual_tree_from_db()
            
            if not db_roots:
                self.status_label.setText("상태: DB에 데이터가 없습니다.")
                self.set_loading(False)
                return

            # 2. RootItem 생성 (tree 필드에 db_roots 리스트 자체를 저장)
            self.current_root = RootItem(
                id="db_root",
                name="AI Virtual Directory",
                tree=db_roots,  # [중요] dict로 변환하지 않고 원본 리스트 저장
                total_files=0   # 개수는 생략하거나 별도 계산
            )

            self.btn_scan.setText("📁 DB 로드 완료")
            
            # 3. 트리 화면 그리기 호출
            self.update_tree_view(db_roots)
            
            self.status_label.setText("상태: 트리 로드 완료.")

        except Exception as e:
            self.status_label.setText(f"오류: {e}")
            print(e)
        finally:
            self.set_loading(False)
    # -------------------------------------------------------------------
    # [추가] 1-1. 화면 초기화 (Clean) 버튼
    # -------------------------------------------------------------------
    # [수정] 화면 초기화 및 DB 삭제 기능
    def handle_clean_click(self):
        """
        DB 데이터를 모두 지우고, 화면도 초기화합니다.
        """
        # 1. DB 삭제 수행
        try:
            conn = get_connection()
            clear_all_data(conn) # DB 싹 지우기
            conn.close()
        except Exception as e:
            self.status_label.setText(f"DB 삭제 실패: {e}")
            return

        # 2. 내부 데이터 초기화
        self.current_root = None
        self.search_results = []

        # 3. UI 컴포넌트 초기화
        self.file_tree.clear()           # [중요] 트리 위젯 비우기
        self.search_results_list.clear() # 검색 결과 비우기
        self.search_input.clear()
        self.current_root_label.setText("현재 루트: (없음)")
        
        # 4. 버튼 및 상태 메시지 원복
        self.btn_scan.setText("📁 DB 로드 (새로고침)")
        self.status_label.setText("상태: 초기화 완료. DB가 비워졌습니다.")
        self.log("화면 및 DB가 초기화되었습니다.")

    # -------------------------------------------------------------------
    # 2. [수정] 디렉토리 스캔 (확장자 분류 X, 모든 경로 반환)
    # -------------------------------------------------------------------
    def scan_and_collect_files(self, dir_path: str) -> tuple[list[str], int]:
        """
        dir_path 이하의 파일을 모두 스캔. (이미지 제외)
        [수정] 확장자별로 분류하지 않고, 모든 파일 경로의 리스트를 반환.
        """
        base = Path(dir_path)
        
        # [수정] tree 딕셔너리 대신 file_paths 리스트 사용
        file_paths: list[str] = []
        total_files = 0

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"}

        for root, dirs, files in os.walk(base):
            for name in files:
                p = Path(root) / name
                ext = p.suffix.lower()
                if ext in image_exts:
                    # 이미지 파일은 제외
                    continue

                total_files += 1
                
                # [수정] 확장자 분류 if문 제거, 그냥 리스트에 추가
                file_paths.append(str(p))

        # [수정] file_paths 리스트와 총 개수 반환
        return file_paths, total_files

    # -------------------------------------------------------------------
    # 3. [수정] (임시) 가상 디렉토리 트리 생성
    # -------------------------------------------------------------------
    def build_virtual_tree_from_clusters(self, file_paths: list[str]) -> dict:
        """
        [수정] 이제 이 함수는 (확장자별 분류된 딕셔너리) 대신
              (경로 리스트)를 받습니다.

        실제로는:
          1) 이 file_paths 리스트를 기반으로 임베딩 계산
          2) 클러스터링
          3) 클러스터 ID / 토픽명 기반 트리 구조 생성

        [임시] "모든 파일"이라는 하나의 카테고리로 묶어서 반환합니다.
               나중에 이 함수를 실제 클러스터링 로직으로 교체하면 됩니다.
        """
        self.log(f"[AI 작업] {len(file_paths)}개 경로 전달받음. (클러스터링 수행)")
        
        # TODO: 여기에 실제 임베딩 + 클러스터링 로직 연결
        
        # 임시로 'all_files'라는 가상 폴더에 모든 파일을 넣음
        if not file_paths:
            return {}
            
        return {
            "all_files": file_paths
        }

    # -------------------------------------------------------------------
    # 4. 파일 리스트 갱신 (update_current_root_view)
    #    (변경 없음 - 'all_files' 키도 잘 처리함)
    # -------------------------------------------------------------------
    # [신규 추가] 실제 트리를 화면에 그리는 함수
    def update_tree_view(self, root_nodes):
        self.file_tree.clear() # 기존 목록 지우기
        
        for node in root_nodes:
            # populate_tree 함수를 호출하여 재귀적으로 그리기
            self.populate_tree(self.file_tree, node)
                
    
    # -------------------------------------------------------------------
    # 5. get_current_root (변경 없음)
    # -------------------------------------------------------------------
    def get_current_root(self) -> RootItem | None:
        return self.current_root

    # -------------------------------------------------------------------
    # 6. 검색 (handle_search_click) (변경 없음)
    # -------------------------------------------------------------------
    def handle_search_click(self):
        query = self.search_input.text().strip()
        root = self.get_current_root() 

        if not query or not root:
            self.search_results = []
            self.search_results_list.clear()
            self.status_label.setText("검색 결과 없음 (검색어 또는 루트 없음)")
            return

        matched = []
        # [참고] root.tree가 {"all_files": [...]} 형태여도 잘 동작합니다.
        for category, paths in root.tree.items():
            for p in paths:
                if query.lower() in Path(p).name.lower():
                    matched.append(p)

        self.search_results = list(map(Path, matched))
        self.search_results_list.clear()

        for p in self.search_results:
            item = QListWidgetItem(str(p.name))
            item.setData(Qt.UserRole, str(p))
            self.search_results_list.addItem(item)

        self.status_label.setText(
            f"검색 결과: {len(self.search_results)}개 (루트: {root.name})"
        )

    # -------------------------------------------------------------------
    # 7. 파일 열기 (handle_file_open) [오류 수정]
    # -------------------------------------------------------------------
    # [수정] 파일 열기 핸들러
    def handle_file_open(self, item: QTreeWidgetItem, column: int):
        # 저장해둔 파일 경로 가져오기
        file_path = item.data(0, Qt.UserRole)
        
        # 파일 경로가 없으면(폴더를 클릭한 경우) 무시하거나 펼치기/접기 토글
        if not file_path:
            # (선택 사항) 폴더 더블클릭 시 펼치기/접기
            item.setExpanded(not item.isExpanded())
            return

        self.status_label.setText(f"파일 열기: {file_path}")

        # 기존 파일 열기 로직 그대로 사용
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":
                import subprocess
                subprocess.run(["open", file_path], check=False)
            else:
                import subprocess
                subprocess.run(["xdg-open", file_path], check=False)
        except Exception as e:
            self.status_label.setText(f"파일 열기 실패: {e}")    
    
    # -------------------------------------------------------------------
    # 8. 추가 기능 버튼 (handle_summary/report_clicked) (변경 없음)
    # -------------------------------------------------------------------
    def handle_summary_clicked(self):
        root = self.get_current_root()
        if not root:
            self.log("[요약] 현재 루트가 없습니다.")
            return
        self.log(f"[요약] (TODO) {root.name} 루트 기반 요약 생성")

    def handle_report_clicked(self):
        root = self.get_current_root()
        if not root:
            self.log("[보고서] 현재 루트가 없습니다.")
            return
        self.log(f"[보고서] (TODO) {root.name} 루트 기반 보고서 제작")

    # -------------------------------------------------------------------
    # 유틸 (set_loading, log) (변경 없음)
    # -------------------------------------------------------------------
    def set_loading(self, flag: bool):
        self.is_loading = flag
        if flag:
            self.status_label.setText("상태: AI가 파일을 분석 중입니다...")
        else:
            self.status_label.setText("상태: 대기 중")

    def log(self, msg: str):
        print(msg)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()