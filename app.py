import sys
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem,
    QFileDialog, QSplitter, QLineEdit,
    QGroupBox
)
from PySide6.QtCore import Qt


# -------------------------------------------------------------------
# React의 roots 비슷한 구조
# -------------------------------------------------------------------
@dataclass
class RootItem:
    id: str
    name: str
    tree: dict = field(default_factory=dict)   # virtual directory tree
    total_files: int = 0


def uuid() -> str:
    import time, random, string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8)) + hex(int(time.time()))[2:]


# -------------------------------------------------------------------
# 메인 윈도우
# -------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("문서 임베딩 / 가상 디렉토리 GUI (임시 버전)")
        self.resize(1200, 700)

        # App.jsx의 state 느낌
        self.roots: list[RootItem] = []
        self.current_root_id: str | None = None
        self.current_path: list[str] = []     # 나중에 트리 구조 쓰면 활용
        self.search_results: list[Path] = []  # 검색 결과
        self.is_loading: bool = False

        # ================= 중앙 전체 레이아웃 =================
        central = QWidget()
        central_layout = QVBoxLayout(central)

        # 상단 상태 라벨
        self.status_label = QLabel("상태: 대기 중")
        central_layout.addWidget(self.status_label)

        # 아래쪽은 3분할 splitter: [왼쪽 사이드바 | 가운데 파일리스트 | 오른쪽 기능패널]
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        # ---------------------------
        # [왼쪽] 디렉토리 스캔 사이드바
        # ---------------------------
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # 디렉토리 스캔 버튼
        self.btn_scan = QPushButton("📁 디렉토리 스캔")
        self.btn_scan.clicked.connect(self.handle_scan_click)
        left_layout.addWidget(self.btn_scan)

        # 여러 루트(스캔 결과) 리스트
        self.roots_list = QListWidget()
        self.roots_list.itemSelectionChanged.connect(self.handle_root_select)
        left_layout.addWidget(self.roots_list, stretch=1)

        # 루트 삭제 버튼
        self.btn_remove_root = QPushButton("선택한 루트 삭제")
        self.btn_remove_root.clicked.connect(self.handle_remove_root)
        left_layout.addWidget(self.btn_remove_root)

        left_layout.addStretch(1)

        # ---------------------------
        # [가운데] 현재 루트 + 가상 디렉토리 파일 리스트
        # ---------------------------
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)

        self.current_root_label = QLabel("현재 루트: (없음)")
        center_layout.addWidget(self.current_root_label)

        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.handle_file_open)
        center_layout.addWidget(self.file_list, stretch=1)

        # ---------------------------
        # [오른쪽] 기능 패널 (검색 + 검색결과 + 추가 기능)
        # ---------------------------
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        feature_group = QGroupBox("기능 패널")
        feature_layout = QVBoxLayout(feature_group)

        # ── [1] 검색 섹션 ────────────────────────────────
        feature_layout.addWidget(QLabel("검색"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (파일명 기준, 임시)")
        btn_search = QPushButton("검색")
        btn_search.clicked.connect(self.handle_search_click)

        feature_layout.addWidget(self.search_input)
        feature_layout.addWidget(btn_search)

        # 검색 결과 리스트 (기능 패널 하단에 붙음)
        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.handle_file_open)
        feature_layout.addWidget(self.search_results_list, stretch=1)

        # 중간 여백 + 아래로 밀기
        feature_layout.addSpacing(10)
        feature_layout.addStretch(1)

        # ── [2] 추가 기능 섹션 (맨 아래) ─────────────────
        feature_layout.addWidget(QLabel("추가 기능"))

        self.btn_summary = QPushButton("요약 생성 (TODO)")
        self.btn_report = QPushButton("보고서 제작 (TODO)")

        self.btn_summary.clicked.connect(self.handle_summary_clicked)
        self.btn_report.clicked.connect(self.handle_report_clicked)

        feature_layout.addWidget(self.btn_summary)
        feature_layout.addWidget(self.btn_report)

        right_layout.addWidget(feature_group, stretch=1)

        # ---------------------------
        # splitter에 [왼 | 중 | 오른] 붙이고 비율 설정
        # ---------------------------
        splitter.addWidget(left_widget)    # 0: 디렉토리 스캔
        splitter.addWidget(center_widget)  # 1: 파일 리스트
        splitter.addWidget(right_widget)   # 2: 기능 패널

        # 좌우 패널 폭 대칭 + 가운데는 넓게
        splitter.setStretchFactor(0, 1)  # 왼쪽
        splitter.setStretchFactor(1, 2)  # 가운데
        splitter.setStretchFactor(2, 1)  # 오른쪽

        # 처음 켤 때: [왼 300 | 중 600 | 오 300] 정도 비율로
        splitter.setSizes([300, 600, 300])

        central_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

    # -------------------------------------------------------------------
    # 1. 디렉토리 스캔 버튼
    # -------------------------------------------------------------------
    def handle_scan_click(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "스캔할 폴더 선택",
            os.path.expanduser("~")
        )
        if not dir_path:
            return

        self.set_loading(True)
        root_name = Path(dir_path).name

        try:
            # (1) 실제 파일들 수집 + 확장자 분류 (이미지 제외)
            categorized_tree, total_files = self.scan_and_collect_files(dir_path)

            # (2) 임베딩 + 클러스터링 후 virtual tree 생성할 자리
            virtual_tree = self.build_virtual_tree_from_clusters(categorized_tree)

            new_root = RootItem(
                id=uuid(),
                name=root_name,
                tree=virtual_tree,
                total_files=total_files,
            )
            self.roots.append(new_root)

            # roots 리스트 UI에 추가
            item = QListWidgetItem(f"{new_root.name} ({new_root.total_files} files)")
            item.setData(Qt.UserRole, new_root.id)
            self.roots_list.addItem(item)

            # 방금 추가한 루트를 현재 루트로 설정
            self.current_root_id = new_root.id
            self.roots_list.setCurrentItem(item)
            self.update_current_root_view()

        except Exception as e:
            self.status_label.setText(f"스캔 실패: {e}")
            print("스캔 실패:", e)
        finally:
            self.set_loading(False)

    # -------------------------------------------------------------------
    # 2. 디렉토리 스캔 + 확장자별 분류 (이미지 제외)
    # -------------------------------------------------------------------
    def scan_and_collect_files(self, dir_path: str):
        """
        dir_path 이하의 파일을 모두 스캔해서 확장자별로 분류.
        이미지(jpg, png, gif 등)는 제외.
        """
        base = Path(dir_path)
        tree = {
            "pdf": [],
            "ppt": [],
            "word": [],
            "excel": [],
            "code": [],
            "text": [],
            "etc": [],
        }
        total_files = 0

        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"}

        for root, dirs, files in os.walk(base):
            for name in files:
                p = Path(root) / name
                ext = p.suffix.lower()
                if ext in image_exts:
                    # 이미지 파일은 가상 디렉토리에서 아예 제외
                    continue

                total_files += 1

                if ext == ".pdf":
                    tree["pdf"].append(str(p))
                elif ext in [".ppt", ".pptx"]:
                    tree["ppt"].append(str(p))
                elif ext in [".doc", ".docx", ".hwp", ".hwpx"]:
                    tree["word"].append(str(p))
                elif ext in [".xls", ".xlsx", ".csv"]:
                    tree["excel"].append(str(p))
                elif ext in [
                    ".py", ".ipynb", ".js", ".ts", ".java",
                    ".c", ".cpp", ".cs", ".go", ".rs", ".php"
                ]:
                    tree["code"].append(str(p))
                elif ext in [".txt", ".md"]:
                    tree["text"].append(str(p))
                else:
                    tree["etc"].append(str(p))

        return tree, total_files

    # -------------------------------------------------------------------
    # 3. (임시) 임베딩 + 클러스터링 → 가상 디렉토리 트리 생성
    # -------------------------------------------------------------------
    def build_virtual_tree_from_clusters(self, categorized_tree: dict) -> dict:
        """
        실제로는:
          1) 모든 파일에 대해 임베딩 계산
          2) 클러스터링 (예: KMeans, HDBSCAN 등)
          3) 클러스터 ID / 토픽명 기반 트리 구조 생성

        지금은 임시로 "확장자별 분류"를 그대로 트리로 사용.
        나중에 이 함수만 갈아끼우면 UI 그대로 두고
        실제 Virtual Directory 로 바뀜.
        """
        # TODO: 여기에 네 임베딩 + 클러스터링 로직을 연결하면 됨.
        return categorized_tree

    # -------------------------------------------------------------------
    # 4. 루트 선택 변경
    # -------------------------------------------------------------------
    def handle_root_select(self):
        item = self.roots_list.currentItem()
        if not item:
            self.current_root_id = None
            self.update_current_root_view()
            return

        root_id = item.data(Qt.UserRole)
        self.current_root_id = root_id
        self.update_current_root_view()

    # 현재 루트에 맞게 가운데 파일 리스트 갱신
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

        # 지금은 "카테고리[가상폴더] - 파일" 구조로만 표시
        for category, paths in root.tree.items():
            for p in paths:
                item = QListWidgetItem(f"[{category}] {Path(p).name}")
                item.setData(Qt.UserRole, p)  # 절대 경로 저장
                self.file_list.addItem(item)

    def get_current_root(self) -> RootItem | None:
        if not self.current_root_id:
            return None
        for r in self.roots:
            if r.id == self.current_root_id:
                return r
        return None

    # -------------------------------------------------------------------
    # 5. 루트 삭제
    # -------------------------------------------------------------------
    def handle_remove_root(self):
        item = self.roots_list.currentItem()
        if not item:
            return

        root_id = item.data(Qt.UserRole)

        # roots 리스트에서 제거
        self.roots = [r for r in self.roots if r.id != root_id]

        # UI 상에서도 제거
        row = self.roots_list.row(item)
        self.roots_list.takeItem(row)

        # currentRootId 정리
        if self.current_root_id == root_id:
            self.current_root_id = None
            self.update_current_root_view()

        self.status_label.setText("선택한 루트가 삭제되었습니다.")

    # -------------------------------------------------------------------
    # 6. 검색 (검색 결과는 오른쪽 기능 패널 하단 리스트에 표시)
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
    # 7. 파일 열기 (Windows/macOS/Linux 모두 지원)
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
            else:  # Linux 계열
                import subprocess
                subprocess.run(["xdg-open", file_path], check=False)
        except Exception as e:
            self.status_label.setText(f"파일 열기 실패: {e}")

    # -------------------------------------------------------------------
    # 8. 기능 패널 추가 기능 버튼 (요약 / 보고서)
    # -------------------------------------------------------------------
    def handle_summary_clicked(self):
        root = self.get_current_root()
        if not root:
            self.log("[요약] 현재 루트가 없습니다.")
            return
        # TODO: 현재 루트 기반 요약 생성 로직 연결
        self.log("[요약] (TODO) 현재 루트 문서들로 요약 생성 로직을 붙이면 됩니다.")

    def handle_report_clicked(self):
        root = self.get_current_root()
        if not root:
            self.log("[보고서] 현재 루트가 없습니다.")
            return
        # TODO: 현재 루트 기반 보고서 생성 로직 연결
        self.log("[보고서] (TODO) 현재 루트 문서들로 보고서 제작 로직을 붙이면 됩니다.")

    # -------------------------------------------------------------------
    # 유틸: 로딩 상태 / 로그
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
