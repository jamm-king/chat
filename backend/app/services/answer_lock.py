"""
사용자별 답변 생성 상태.
AI 계약: Backend 는 사용자별 활성 생성을 하나로 제한하고, 대화 초기화 전의 늦은 답변을 버린다.

서버 메모리에 보관하므로 백엔드 프로세스가 하나일 때만 정확하다 (uvicorn worker 1개 기준).
"""
import threading
import uuid
from typing import Dict, Optional

_lock = threading.Lock()
_active: Dict[str, str] = {} #user_id -> 진행 중인 생성의 토큰

def start(user_id: str) -> Optional[str]:
    """생성을 시작하고 토큰을 돌려준다. 이미 진행 중이면 None."""
    with _lock:
        if user_id in _active:
            return None
        token = str(uuid.uuid4())
        _active[user_id] = token
        return token


def is_current(user_id: str, token: str) -> bool:
    """그사이 대화가 초기화되지 않았으면 True."""
    with _lock:
        return _active.get(user_id) == token


def finish(user_id: str, token: str) -> None:
    """생성이 끝나면 표시를 지운다. 초기화 뒤 새로 시작한 생성의 표시는 건드리지 않는다."""
    with _lock:
        if _active.get(user_id) == token:
            del _active[user_id]


def cancel(user_id: str) -> None:
    """대화 초기화: 진행 중인 생성을 무효로 만든다."""
    with _lock:
        _active.pop(user_id, None)