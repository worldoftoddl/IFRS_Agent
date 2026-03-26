"""kiwipiepy 기반 한국어 토크나이저.

BM25 인덱싱/검색을 위해 한국어 텍스트를 형태소 분석하여
공백 구분된 토큰 문자열로 변환한다.
PostgreSQL의 to_tsvector('simple', ...) / plainto_tsquery('simple', ...)와 함께 사용.
"""

import threading

from kiwipiepy import Kiwi

_kiwi: Kiwi | None = None
_kiwi_lock = threading.Lock()


def _get_kiwi() -> Kiwi:
    """싱글턴 Kiwi 인스턴스 반환 (thread-safe)."""
    global _kiwi
    if _kiwi is None:
        with _kiwi_lock:
            if _kiwi is None:
                _kiwi = Kiwi()
    return _kiwi


def tokenize_for_index(text: str) -> str:
    """문서 인덱싱용 토큰화. content_text → 형태소 분리된 공백 문자열.

    모든 토큰의 form을 공백으로 결합하여 반환.
    to_tsvector('simple', result)로 인덱싱하면 형태소 단위 매칭 가능.
    """
    if not text or not text.strip():
        return ""
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    return " ".join(t.form for t in tokens)


def tokenize_for_query(text: str) -> str:
    """검색 쿼리용 토큰화. 문서와 동일한 형태소 분석 적용.

    plainto_tsquery('simple', result)로 검색하면 형태소 단위 매칭 가능.
    """
    if not text or not text.strip():
        return ""
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    return " ".join(t.form for t in tokens)
