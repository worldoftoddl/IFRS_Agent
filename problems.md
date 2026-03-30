# 진단된 문제점 및 개선 과제

## BM25 토큰화 실패 — `simple` config 한계 (해결됨)

**현상**: BM25 단독 평가 시 Recall=0.000, MRR=0.000 (36문항 전체 실패)

**원인**: PostgreSQL `simple` config은 공백 분리만 수행.
한국어 교착어 특성상 "충당부채는", "이행가치란" 같은 조사 붙은 쿼리가
문서의 "충당부채", "이행가치"와 매칭되지 않음.

**해결**: kiwipiepy 한국어 형태소 분석 전처리 도입 (커밋 `d5609cf`).
- `app/tokenizer.py`: kiwipiepy 형태소 분석 + 158개 K-IFRS 사용자 사전 (`app/kiwi_user_dict.txt`)
- tsvector 생성: `content_text` → kiwipiepy 형태소 분석 → `to_tsvector('simple', 토큰문자열)`
- 검색 시: 쿼리도 동일하게 kiwipiepy 전처리 → `plainto_tsquery('simple', 토큰문자열)`
- 마이그레이션: `app/migrations/002_rebuild_tsvector_kiwi.py`로 content_tsv 재빌드

**결과**: BM25 단독 Recall 0.000 → 0.158, MRR 0.000 → 0.209로 개선.
하이브리드 RRF에서 BM25가 실제로 기여하게 됨.
