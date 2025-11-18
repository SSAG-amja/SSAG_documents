# app.py (v3. 클린 기능 추가 및 스캔 로직 변경)
import sys
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path
import time, random, string # uuid용

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QSplitter, QLineEdit,
    QGroupBox
)
from PySide6.QtCore import Qt


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
        # [오른쪽] 파일 리스트
        # ---------------------------
        right_panel_widget = QWidget()
        right_layout = QVBoxLayout(right_panel_widget)

        self.current_root_label = QLabel("현재 루트: (없음)")
        right_layout.addWidget(self.current_root_label)

        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.handle_file_open)
        right_layout.addWidget(self.file_list, stretch=1)

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

    # -------------------------------------------------------------------
    # 1. 디렉토리 스캔 버튼
    # -------------------------------------------------------------------
    def handle_scan_click(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "스캔할 폴더 선택", os.path.expanduser("~")
        )
        if not dir_path:
            return

        self.set_loading(True)
        root_name = Path(dir_path).name

        try:
            # [수정] 확장자 분류(categorized_tree) 대신 파일 경로 리스트(file_paths)를 받음
            file_paths, total_files = self.scan_and_collect_files(dir_path)

            # [수정] file_paths 리스트를 클러스터링 함수로 전달
            # (이 함수가 나중에 AI 작업을 수행하고 가상 트리를 반환할 부분)
            virtual_tree = self.build_virtual_tree_from_clusters(file_paths)

            self.current_root = RootItem(
                id=uuid(),
                name=root_name,
                tree=virtual_tree,
                total_files=total_files,
            )
            
            # [수정] 버튼 비활성화 로직 *삭제* -> 계속 활성화됨
            self.btn_scan.setText(f"📁 {root_name} (스캔됨)")

            self.update_current_root_view()

        except Exception as e:
            self.status_label.setText(f"스캔 실패: {e}")
            print("스캔 실패:", e)
        finally:
            self.set_loading(False)

    # -------------------------------------------------------------------
    # [추가] 1-1. 화면 초기화 (Clean) 버튼
    # -------------------------------------------------------------------
    def handle_clean_click(self):
        """
        현재 스캔된 루트 정보와 파일 목록, 검색 결과를 모두 지우고
        초기 상태로 되돌립니다.
        """
        self.current_root = None
        self.search_results = []

        # UI 초기화
        self.update_current_root_view() # 파일 목록 및 루트 라벨 초기화
        self.search_results_list.clear()
        self.search_input.clear()
        
        # 버튼 텍스트 원복
        self.btn_scan.setText("📁 디렉토리 스캔")
        
        self.status_label.setText("상태: 대기 중. 새 디렉토리를 스캔하세요.")
        self.log("화면이 초기화되었습니다.")

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
    def update_current_root_view(self):
        root = self.get_current_root() 
        if not root:
            self.current_root_label.setText("현재 루트: (없음)")
            self.file_list.clear()
            return

        self.current_root_label.setText(
            f"현재 루트: {root.name} (총 {root.total_files}개 파일)"
        )
        self.file_list.clear()

        # [참고] root.tree가 {"all_files": [...]} 형태가 되므로,
        # '📂 ALL_FILES' 라는 헤더와 그 아래 파일 목록이 표시됩니다.
        for category, paths in root.tree.items():
            if not paths:
                continue
            
            header = QListWidgetItem(f"📂 {category.upper()} ({len(paths)}개)")
            header.setFlags(header.flags() & ~Qt.ItemIsSelectable)
            header.setFlags(header.flags() & ~Qt.ItemIsEnabled)
            self.file_list.addItem(header)

            for p in paths:
                item = QListWidgetItem(f"    📄 {Path(p).name}")
                item.setData(Qt.UserRole, p)
                self.file_list.addItem(item)

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
    def handle_file_open(self, item: QListWidgetItem):
        file_path = item.data(Qt.UserRole)
        if not file_path:
            return

        self.status_label.setText(f"파일 열기: {file_path}")

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":  # macOS
                import subprocess
                subprocess.run(["open", file_path], check=False)
            else:  # Linux 계열 (SameSite 오타 수정)
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