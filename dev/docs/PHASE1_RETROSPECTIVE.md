# Phase 1 회고 — 파라미터 튜닝으로 Recall 개선 시도

**기간**: 2026-03-30
**결론**: 실패. Recall/MRR 개선 없이 latency만 증가.

## 시도한 것

### 1. Weighted RRF (w_dense=0.7, w_bm25=0.3)

BM25 단독 Recall이 0.158로 Dense(0.563) 대비 매우 낮으므로,
Dense 가중치를 높이면 결과가 개선될 것으로 기대했다.

**결과**: Recall 0.540 → 0.535 (변화 없음).
BM25가 원래 기여가 거의 0이라 가중치를 줄여도 영향이 없었다.

### 2. Pool 확대 (30 → 50)

Reranker에 더 많은 후보를 제공하면 정답 문단이 pool 안에 들어올 확률이 높아질 것으로 기대했다.

**결과**: 이전 pool50 평가(Recall 0.563)와 비교해 유의미한 차이 없음.
Pool 크기는 이미 충분했다.

### 3. 인접 문단 확장 (±1 문단 자동 포함)

핵심 문제가 "문단 14는 찾지만 15, 16을 놓침"이었으므로,
검색된 문단의 인접 문단을 DB에서 조회해 후보에 추가했다.

**결과**: 후보 풀 내 Recall은 0.766까지 상승 (정답 문단이 후보에 있음 확인).
하지만 top-10 선별 시 Reranker가 정답을 올려주지 못해 최종 Recall 미개선.

## 최종 수치

| Config | Recall@10 | MRR | StdAcc | Latency |
|--------|-----------|-----|--------|---------|
| baseline (원복됨) | 0.540 | 0.509 | 0.861 | 1.11s |
| weighted_rrf | 0.535 | 0.509 | 0.861 | 1.04s |
| phase1 (전체) | 0.520 | 0.402 | 0.889 | 3.02s |

## 남은 코드

- `_step2_search_hybrid`에 `w_dense`, `w_bm25` 파라미터 추가됨 (기본값 1.0/1.0 → 하위호환)
- `_expand_adjacent_paragraphs` 함수 추가됨 (search_ifrs에서는 미사용, 추후 활용 가능)
- `eval/evaluate.py`에 `weighted_rrf`, `expand_adjacent`, `phase1` 설정 추가됨
- 테스트 13개 추가 (`tests/test_phase1_recall.py`) — 전체 107개 통과

## 교훈

1. **BM25는 현재 파이프라인에서 사실상 무기여**. 가중치를 0으로 해도 결과가 같다.
   원인: kiwipiepy 형태소 분석 후에도 BM25 Recall이 0.158에 불과.
2. **Cohere Reranker는 Recall을 떨어뜨린다**. StdAcc는 올리지만 top-10 문단 선별에서 오히려 정답을 밀어냄.
   Trial key rate limit(10회/분)도 실용성에 장애.
3. **인접 문단 확장은 "찾기"는 성공했으나 "선별"이 안 됨**.
   후보 풀(Recall@pool=0.766)은 충분한데, top-10으로 줄일 때 정답이 탈락.
   근본 원인: 임베딩이 인접 문단 간 유사도를 제대로 구분하지 못함.
4. **파라미터 튜닝의 한계**. 검색 품질의 병목은 파라미터가 아니라 임베딩 품질.
   Recall을 0.7+ 올리려면 임베딩 자체를 개선해야 한다 (Contextual Retrieval 등).

## 다음 단계

Phase 2: Contextual Retrieval — 각 chunk에 기준서명+섹션 context prefix를 붙여 re-embedding.
임베딩이 "이 문단이 어떤 기준서의 어느 섹션에 속하는지" 알게 되면,
인접 문단 간 구분력이 높아지고 Recall이 개선될 것으로 기대.
