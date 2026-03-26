# 진단된 문제점 및 개선 과제

## BM25 토큰화 실패 — `simple` config 한계 (미해결)

**현상**: BM25 단독 평가 시 Recall=0.000, MRR=0.000 (36문항 전체 실패)

**원인**: PostgreSQL `simple` config은 공백 분리만 수행.
한국어 교착어 특성상 "충당부채는", "이행가치란" 같은 조사 붙은 쿼리가
문서의 "충당부채", "이행가치"와 매칭되지 않음.

**결과**: 하이브리드 검색(RRF)에서 BM25 기여가 0 — dense_only와 동일한 결과.

**해결 방안**: `kiwipiepy`로 한국어 형태소 분석 전처리.
- tsvector 생성 시: `content_text` → kiwipiepy 형태소 분석 → 분리된 토큰을 `simple` config으로 인덱싱
- 검색 시: 쿼리도 동일하게 kiwipiepy 전처리 → tsquery 생성
- 마이그레이션: content_tsv 재생성 + 트리거 수정

**우선순위**: Phase 3 (Reranker) 후 진행. 리랭커 단독 효과, BM25 수정 효과, 합산 효과를 분리 측정.
