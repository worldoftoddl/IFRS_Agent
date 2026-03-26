# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

K-IFRS(한국채택국제회계기준) 벡터 DB를 활용한 **질의응답 Agent** 프로젝트.
LangGraph + DeepAgents 프레임워크 기반으로, 사용자 질문에 대해 관련 기준서를 검색하고 Claude가 답변을 생성한다.

- **백엔드**: `deepagents` (`create_deep_agent`) + LangGraph 서버 (`langgraph dev`)
- **프론트엔드**: `deep-agents-ui` (Next.js 16) — `ui/` 디렉토리
- **DB**: PostgreSQL+pgvector (`kifrs` DB) — `_IFRS_parsing` 프로젝트에서 구축
- **LLM**: Claude Sonnet 4.6 (`anthropic:claude-sonnet-4-6`)
- **임베딩**: Upstage Solar (`embedding-query`, 4096차원)
- **Reranker**: Cohere `rerank-v3.5`
- **토크나이저**: kiwipiepy + 158개 K-IFRS 사용자 사전

## 저장소 구조

```
├── pyproject.toml              ← 프로젝트 설정 + 의존성 (hatchling 빌드)
├── langgraph.json              ← LangGraph 서버 설정 (ifrs-agent 그래프)
├── .env                        ← 환경변수 (API 키, DB URL) — .gitignore
├── app/
│   ├── __init__.py
│   ├── agent.py                ← create_deep_agent() 메인 진입점
│   ├── tools.py                ← 4개 도구 + 내부 검색 파이프라인
│   ├── db.py                   ← psycopg ConnectionPool + pgvector (thread-safe)
│   ├── embedder.py             ← Upstage embedding-query 래퍼 (thread-safe)
│   ├── prompts.py              ← K-IFRS 전문가 시스템 프롬프트
│   ├── tokenizer.py            ← kiwipiepy 형태소 분석 + 사용자 사전
│   ├── reranker.py             ← Cohere rerank-v3.5 래퍼 (graceful degradation)
│   ├── multi_query.py          ← Multi-Query 변형 생성 (Haiku, 비교용)
│   ├── extract_terms.py        ← definitions_text에서 K-IFRS 용어 추출
│   ├── kiwi_user_dict.txt      ← 158개 K-IFRS 복합명사 사전
│   └── migrations/
│       ├── 001_add_tsvector.sql         ← tsvector 컬럼 + GIN 인덱스 (초기)
│       └── 002_rebuild_tsvector_kiwi.py ← kiwipiepy 토큰화로 tsvector 재빌드
├── eval/
│   ├── golden_dataset.json     ← 36문항 평가 데이터셋
│   ├── evaluate.py             ← Recall/MRR/StdAcc 평가 프레임워크
│   └── results/                ← 평가 결과 JSON 파일들
├── tests/                      ← 94개 테스트
│   ├── test_step2_authority.py
│   ├── test_multi_standard_search.py
│   ├── test_prompts.py
│   ├── test_similarity_threshold.py
│   ├── test_tsvector.py
│   ├── test_hybrid_search.py
│   ├── test_evaluation.py
│   ├── test_param_tuning.py
│   ├── test_reranker.py
│   ├── test_multi_query.py
│   ├── test_tokenizer.py
│   └── test_user_dict.py
├── problems.md                 ← 진단된 문제점 및 개선 과제
├── DB_USAGE_GUIDE.md           ← 벡터 DB 사용 가이드
├── DB_QUALITY_REPORT.md        ← IAS 본문 누락 진단 리포트
├── DB_QUALITY_REPORT_RESPONSE.md ← 파싱 수정 대응 리포트
├── ui/                         ← deep-agents-ui (git clone, .gitignore)
└── CLAUDE.md
```

## 빌드 & 실행

```bash
# --- 의존성 설치 ---
python3 -m venv .venv && source .venv/bin/activate
pip install -e .              # 프로덕션 의존성
pip install -e ".[dev]"       # + ruff, pytest, langgraph-cli

# --- DB 마이그레이션 (DB 재적재 후 반드시 실행) ---
python app/extract_terms.py                        # K-IFRS 용어 사전 생성
python app/migrations/002_rebuild_tsvector_kiwi.py  # kiwipiepy tsvector 재빌드

# --- 테스트 ---
python -m pytest tests/ -v    # 94개 전체 통과 확인

# --- 평가 ---
python eval/evaluate.py baseline                   # 36문항 평가

# --- LangGraph 서버 시작 (터미널 1) ---
langgraph dev --no-browser    # http://127.0.0.1:2024

# --- 프론트엔드 (터미널 2) ---
cd ui && yarn install && yarn dev   # http://localhost:3000
# 설정: Deployment URL = http://127.0.0.1:2024, Assistant ID = ifrs-agent

# --- 환경변수 (.env) ---
# ANTHROPIC_API_KEY=...       ← Claude API
# UPSTAGE_API_KEY=...         ← Upstage Solar Embedding
# COHERE_API_KEY=...          ← Cohere Reranker
# DATABASE_URL=dbname=kifrs   ← 로컬 peer/trust 인증
# LANGCHAIN_API_KEY=...       ← LangSmith (선택)
```

## 아키텍처

### Agent 구성 (`app/agent.py`)

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[search_ifrs, search_ifrs_examples, search_ifrs_rationale, get_standard_info],
    system_prompt=SYSTEM_PROMPT,
    name="kifrs-agent",
)
```

### 검색 파이프라인 (`search_ifrs`)

```
사용자 질문
  → embed_query()                        Upstage embedding-query
  → Step 1: _step1_identify_standard     standard_summaries top-5
  → 유사도 임계값 필터 (< 0.2 차단)
  → Step 2: _step2_search_hybrid         BM25(kiwipiepy) + Dense 순수 RRF
  │   ├── Dense CTE: embedding 코사인 거리 top-pool
  │   ├── BM25 CTE: content_tsv @@ plainto_tsquery (kiwipiepy 토큰화)
  │   ├── FULL OUTER JOIN → rrf_score = 1/(60+rank_dense) + 1/(60+rank_bm25)
  │   └── pool=20 (reranker에 충분한 후보 제공)
  → Step 2.5: Cohere rerank-v3.5         pool 20 → top 10 재정렬
  → primary_id 판정                      Counter로 최다 기준서 선택
  → 컨텍스트 포맷팅                       용어 정의 자동 주입 + 문단 (기준서 ID 표시)
```

### 도구별 역할

| 도구 | 용도 | 호출 시점 |
|------|------|----------|
| `search_ifrs` | 하이브리드 검색 + Reranker | 항상 (기본) |
| `search_ifrs_examples` | IE 적용사례 (paragraph_links) | 실무 처리 방법 필요 시 |
| `search_ifrs_rationale` | BC 결론도출근거 (paragraph_links) | 기준 제정 배경 질문 |
| `get_standard_info` | 기준서 메타데이터 | 기본 정보 확인 |

### 핵심 설계 결정

- **하이브리드 RRF**: Dense + BM25(kiwipiepy) 순수 RRF. 가중치 없음 — 순위만 사용.
- **Cohere Reranker**: RRF 후보 20개를 rerank-v3.5로 재정렬 → top-10. 실패 시 RRF 유지.
- **kiwipiepy 사용자 사전**: 158개 K-IFRS 복합명사 등록. "충당부채", "사용권자산" 등 보존.
- **복수 기준서 통합 검색**: top-5 후보를 UNNEST JOIN 단일 쿼리로 검색.
- **authority 동적 필터**: `authority <= base_authority`. 개념체계(3), 실무서(4) 검색 가능.
- **유사도 임계값 0.2**: 회계 무관 질문 차단.

### BM25 토큰화 (`app/tokenizer.py`)

- **kiwipiepy** 형태소 분석 + 158개 사용자 사전 (`app/kiwi_user_dict.txt`)
- `tokenize_for_index()`: 문서 인덱싱용 (content_text → 형태소 공백 문자열)
- `tokenize_for_query()`: 검색 쿼리용 (동일 분석)
- PostgreSQL `to_tsvector('simple', 토큰문자열)` + GIN 인덱스
- DB 재적재 시 `002_rebuild_tsvector_kiwi.py` 실행 필요 (트리거 없음)

### 평가 프레임워크 (`eval/`)

- **Golden Dataset**: 36문항, 15개 기준서, 8개 카테고리, easy/medium/hard
- **지표**: Recall@10, MRR, Standard Accuracy
- **SEARCH_CONFIGS**: 10개 설정 (baseline, rrf_k변형, dense_only, bm25_only, reranker, multi_query 등)
- **최신 결과**: baseline Recall=0.540, reranker Recall=0.539 StdAcc=0.889

## 핵심 기술 스택 (2026.03 기준)

| 패키지 | 용도 |
|--------|------|
| `deepagents` | Agent 프레임워크 (LangGraph 기반) |
| `langgraph` | 상태 관리 + 그래프 런타임 |
| `langchain-anthropic` | Claude 모델 통합 |
| `cohere` | Reranker (rerank-v3.5) |
| `kiwipiepy` | 한국어 형태소 분석 (BM25 토큰화) |
| `psycopg` + `pgvector` | PostgreSQL + 벡터 검색 |
| `openai` | Upstage Solar Embedding (호환 API) |
| `deep-agents-ui` | 프론트엔드 (Next.js 16) |

## 코드 품질

- `ruff check app/ eval/` — 전체 통과
- `python -m pytest tests/` — 94개 테스트 전체 통과
- 모든 SQL은 파라미터화 (`%s`, `ANY(%s)`, `UNNEST`, named `%(key)s`)
- thread-safe 싱글턴 (double-checked locking): db, embedder, tokenizer, reranker

## K-IFRS 도메인 지식

### 권위 수준과 DB authority 매핑

| Level | 구성요소 | DB `authority` | DB `base_authority` |
|-------|---------|---------------|---------------------|
| 1 (Authoritative) | 기준서 본문, 적용지침, 정의, 경과규정, 해석서 | 1 | 1 |
| 3 (Framework) | 개념체계 | 3 | 3 |
| 4 (Non-authoritative) | 결론도출근거(BC), 적용사례(IE), 실무서 | 4 | 4 |

### DB 스키마 (kifrs)

| 테이블 | 용도 | 행 수 |
|--------|------|------|
| `standards` | 기준서 메타데이터 | 63 |
| `chunks` | 검색 대상 청크 (embedding + content_tsv) | 16,616 |
| `standard_summaries` | 기준서 식별용 요약 | 63 |
| `footnotes` | 각주 | 852 |
| `paragraph_links` | BC/IE → 본문 참조 링크 | 7,952 |

## 관련 프로젝트

- **`_IFRS_parsing`** (`/home/shin/Project/_IFRS_parsing/`): docx → 마크다운 → 벡터 DB 적재 파이프라인
- **DB 사용 가이드**: `DB_USAGE_GUIDE.md`
- **DB 품질 리포트**: `DB_QUALITY_REPORT.md`, `DB_QUALITY_REPORT_RESPONSE.md`
