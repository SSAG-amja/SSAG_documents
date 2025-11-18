import subprocess
import sys
import os

# 실행할 파일 목록 (순서 중요: 데이터 캐시 -> 클러스터링 -> 라벨링 -> 계층 구조)
WORKFLOW_STEPS = [
    "vectorPull.py",
    "Clustering.py",
    "ClusterLabel.py",
    "ClusterCategory.py"
]

def run_workflow():
    """전체 RAG 문서 클러스터링 및 계층 구조 생성 워크플로우를 순차적으로 실행합니다."""
    
    # 1. 스크립트 파일이 위치한 디렉토리 경로 계산
    # '__file__'은 현재 실행 중인 파일의 경로를 나타냅니다.
    try:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        # 인터프리터에서 실행될 경우를 대비한 대체 경로
        SCRIPT_DIR = os.path.abspath(os.path.dirname(sys.argv[0]))
        
    
    # 2. 현재 작업 디렉토리를 스크립트 디렉토리로 변경
    # 이 단계를 통해 모든 파일 입출력이 이 디렉토리를 기준으로 이루어집니다.
    os.chdir(SCRIPT_DIR)
    
    print("--- 🚀 문서 클러스터링 및 계층 구조 자동화 워크플로우 시작 ---")
    print(f"✅ 현재 작업 디렉토리가 다음으로 설정되었습니다: {SCRIPT_DIR}")
    
    # 시스템에 설치된 Python 실행 경로를 사용
    python_executable = sys.executable or "python"

    for step_index, script_name in enumerate(WORKFLOW_STEPS):
        
        print(f"\n=======================================================")
        print(f"[{step_index + 1}/{len(WORKFLOW_STEPS)}] {script_name} 실행 중...")
        print(f"=======================================================")
        
        try:
            # subprocess.run을 사용하여 외부 스크립트 실행
            subprocess.run(
                [python_executable, script_name],
                check=True,
                text=True,
                stderr=sys.stderr,
                stdout=sys.stdout
            )
            
            print(f"✅ {script_name} 실행 완료.")
            
        except FileNotFoundError:
            print(f"❌ 오류: 스크립트 파일 '{script_name}'을(를) 찾을 수 없습니다.", file=sys.stderr)
            print("워크플로우를 중단합니다. 모든 파일이 스크립트와 같은 디렉토리에 있는지 확인하십시오.", file=sys.stderr)
            return False
            
        except subprocess.CalledProcessError as e:
            print(f"❌ 오류: {script_name} 실행 중 실패 (오류 코드: {e.returncode}).", file=sys.stderr)
            print("자세한 오류 메시지는 위에 표시된 스크립트 출력을 참조하십시오.", file=sys.stderr)
            print("워크플로우를 중단합니다.", file=sys.stderr)
            return False
            
    print("\n\n--- 🎉 워크플로우 전체 성공! 🎉 ---")
    return True