import requests
import json
import sys

# -----------------------------
# 1. 설정 (사용자 환경에 맞게 수정)
# -----------------------------
from core.config import SOLAR_API_KEY

# 현재 스크립트들에 사용된 키를 복사하세요.
SOLAR_LLM_ENDPOINT = "https://api.upstage.ai/v1/chat/completions"
TEST_PROMPT = "업스테이지의 Solar 모델에 대해 한 문장으로 설명해 주세요."

# -----------------------------
# 2. 실행 함수
# -----------------------------

def check_solar_api_call():
    """Solar LLM API에 테스트 요청을 보내 응답 상태와 내용을 확인합니다."""
    
    headers = {
        "Authorization": f"Bearer {SOLAR_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "solar-pro2", # 현재 사용 중인 모델명
        "messages": [{"role": "user", "content": TEST_PROMPT}],
        "temperature": 0.1,
        "max_tokens": 512
    }
    
    print(f"--- Solar LLM API 호출 테스트 시작 ---", file=sys.stderr)
    print(f"엔드포인트: {SOLAR_LLM_ENDPOINT}", file=sys.stderr)
    
    try:
        # API 호출 (타임아웃 10초 설정)
        response = requests.post(
            SOLAR_LLM_ENDPOINT, 
            headers=headers, 
            json=payload, 
            timeout=10
        )
        
        # 1. HTTP 상태 코드 확인
        print(f"\n[HTTP 상태 코드] : {response.status_code}", file=sys.stderr)
        
        # 2. 응답 내용 디버깅
        response_json = response.json()
        
        if response.status_code == 200:
            # 성공 응답
            summary = response_json['choices'][0]['message']['content'].strip()
            print("✅ 호출 성공", file=sys.stderr)
            print(f"----------------------------------------", file=sys.stderr)
            print(f"LLM 응답 요약: {summary[:100]}...", file=sys.stderr)
            print(f"----------------------------------------", file=sys.stderr)
            return True
        else:
            # 오류 응답
            print(f"❌ 호출 실패 (HTTP {response.status_code})", file=sys.stderr)
            print(f"오류 상세: {response.text}", file=sys.stderr)
            
            if response.status_code in [401, 403]:
                print("\n💡 문제 추정: API 키(Authorization)가 잘못되었거나 만료/비활성화되었습니다.", file=sys.stderr)
            
            return False

    except requests.exceptions.RequestException as e:
        # 네트워크 또는 타임아웃 오류
        print(f"\n❌ 네트워크/연결 오류 발생: {e}", file=sys.stderr)
        print("\n💡 문제 추정: 외부 API로의 통신이 차단되었거나 네트워크가 불안정합니다.", file=sys.stderr)
        return False
    except Exception as e:
        # 기타 파싱 오류
        print(f"\n❌ 알 수 없는 오류: {e}", file=sys.stderr)
        return False

# -----------------------------
# 3. 실행
# -----------------------------
if __name__ == "__main__":
    check_solar_api_call()