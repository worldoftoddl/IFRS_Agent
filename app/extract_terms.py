"""K-IFRS 용어 추출 — standard_summaries.definitions_text에서 복합명사 추출.

결과를 app/kiwi_user_dict.txt에 저장.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection

DICT_PATH = Path(__file__).parent / "kiwi_user_dict.txt"

# 사용자 제안 용어 (DB에서 자동 추출되지 않는 핵심 복합명사)
MANUAL_TERMS = [
    "사용권자산",
    "리스부채",
    "계약자산",
    "계약부채",
    "이연법인세",
    "이연법인세자산",
    "이연법인세부채",
    "이행가치",
    "현행원가",
    "사용가치",
    "순실현가능가치",
    "당기손익",
    "기타포괄손익",
    "매출채권",
    "대손충당금",
    "감가상각누계액",
    "현금창출단위",
    "금융부채",
    "금융자산",
    "지분상품",
    "확정급여채무",
    "확정급여제도",
    "확정기여제도",
    "순확정급여부채",
    "순확정급여자산",
    "사업결합",
    "연결재무제표",
    "별도재무제표",
    "비연결재무제표",
    "결합재무제표",
    "현금흐름표",
    "재무상태표",
    "포괄손익계산서",
    "손익계산서",
    "자본변동표",
    "주당이익",
    "희석주당이익",
    "기본주당이익",
]


def extract_from_db() -> set[str]:
    """definitions_text에서 '용어: 정의' 패턴의 용어 추출."""
    terms: set[str] = set()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT definitions_text FROM standard_summaries "
            "WHERE definitions_text IS NOT NULL AND length(definitions_text) > 10"
        ).fetchall()

    for (dtext,) in rows:
        for line in dtext.split("\n"):
            line = line.strip()
            m = re.match(r"^([가-힣][가-힣\s]{1,20})\s*[:：]", line)
            if m:
                term = m.group(1).strip()
                if 2 <= len(term) <= 12 and " " not in term:
                    terms.add(term)
    return terms


def main():
    db_terms = extract_from_db()
    all_terms = db_terms | set(MANUAL_TERMS)

    # 1글자 제거, 정렬
    all_terms = {t for t in all_terms if len(t) >= 2}
    sorted_terms = sorted(all_terms)

    DICT_PATH.write_text("\n".join(sorted_terms) + "\n")
    print(f"DB 추출: {len(db_terms)}개")
    print(f"수동 추가: {len(MANUAL_TERMS)}개")
    print(f"총 저장: {len(sorted_terms)}개 → {DICT_PATH}")


if __name__ == "__main__":
    main()
