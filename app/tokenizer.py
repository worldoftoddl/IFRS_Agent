"""kiwipiepy 기반 한국어 토크나이저 + K-IFRS 사용자 사전.

기존 tsvector 유산과 용어 추출 보조 작업을 위해 한국어 텍스트를
형태소 분석하여 공백 구분된 토큰 문자열로 변환한다.
K-IFRS 복합명사(충당부채, 사용권자산 등)는 사용자 사전에 등록하여 보존.
"""

import logging
import threading
from pathlib import Path

from kiwipiepy import Kiwi

logger = logging.getLogger(__name__)

_kiwi: Kiwi | None = None
_kiwi_lock = threading.Lock()

DICT_PATH = Path(__file__).parent / "kiwi_user_dict.txt"


def _load_user_dict(kiwi: Kiwi) -> int:
    """사용자 사전 파일에서 K-IFRS 복합명사를 등록."""
    if not DICT_PATH.exists():
        logger.warning("사용자 사전 파일 없음: %s", DICT_PATH)
        return 0

    count = 0
    for line in DICT_PATH.read_text().splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            kiwi.add_user_word(term, "NNP")
            count += 1

    logger.info("K-IFRS 사용자 사전 %d개 용어 등록", count)
    return count


def _get_kiwi() -> Kiwi:
    """싱글턴 Kiwi 인스턴스 반환 (thread-safe, 사용자 사전 적용)."""
    global _kiwi
    if _kiwi is None:
        with _kiwi_lock:
            if _kiwi is None:
                kiwi = Kiwi()
                _load_user_dict(kiwi)
                _kiwi = kiwi
    return _kiwi


def tokenize_for_index(text: str) -> str:
    """문서 인덱싱용 토큰화. content_text → 형태소 분리된 공백 문자열.

    K-IFRS 복합명사는 사용자 사전에 의해 보존됨.
    """
    if not text or not text.strip():
        return ""
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    return " ".join(t.form for t in tokens)


def tokenize_for_query(text: str) -> str:
    """검색 쿼리용 토큰화. 문서와 동일한 형태소 분석 적용.

    현재 K-IFRS 런타임 검색은 pgvector Dense 검색을 사용하므로 이 함수는
    legacy tsvector 유산과 보조 스크립트용으로만 남아 있다.
    """
    if not text or not text.strip():
        return ""
    kiwi = _get_kiwi()
    tokens = kiwi.tokenize(text)
    return " ".join(t.form for t in tokens)
