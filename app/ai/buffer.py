"""
텍스트 버퍼 — STT 확정 문장을 최근 N초 분량만 들고 있는다.

현장 음성은 한 안내 방송이 여러 조각으로 나뉘어 들어온다.
("화재가 발생했..." / "...비상구로 대피해 주십시오")
그래서 마지막 조각 하나가 아니라 최근 몇 초를 묶어서 LLM 에 넘긴다.
"""
import time
from collections import deque
from typing import Callable


class TextBuffer:
    def __init__(self, window_sec: float = 10, clock: Callable[[], float] = time.monotonic):
        self.window_sec = window_sec
        self._clock = clock
        self._items: deque[tuple[float, str]] = deque()

    def add(self, text: str) -> None:
        text = text.strip()
        if text:
            self._items.append((self._clock(), text))
        self._evict()

    def text(self) -> str:
        self._evict()
        return " ".join(t for _, t in self._items)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        self._evict()
        return len(self._items)

    def _evict(self) -> None:
        cutoff = self._clock() - self.window_sec
        while self._items and self._items[0][0] < cutoff:
            self._items.popleft()
