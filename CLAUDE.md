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

## 저장소 구조

```
├── pyproject.toml              ← 프로젝트 설정 + 의존성 (hatchling 빌드)
├── langgraph.json              ← LangGraph 서버 설정 (ifrs-agent 그래프)
├── .env                        ← 환경변수 (API 키, DB URL) — .gitignore
├── app/
│   ├── __init__.py
│   ├── agent.py                ← create_deep_agent() 메인 진입점
│   ├── tools.py                ← 4개 도구 + 내부 검색 파이프라인
│   ├── db.py                   ← psycopg ConnectionPool + pgvector (thread-safe 싱글턴)
│   ├── embedder.py             ← Upstage embedding-query 래퍼 (thread-safe 싱글턴)
│   └── prompts.py              ← K-IFRS 전문가 시스템 프롬프트
├── tests/
│   ├── test_step2_authority.py  ← authority 동적 필터 테스트 (6개)
│   ├── test_multi_standard_search.py ← 복수 기준서 통합 검색 테스트 (7개)
│   ├── test_prompts.py          ← 프롬프트 필수 지침 테스트 (7개)
│   └── test_similarity_threshold.py  ← 유사도 임계값 테스트 (6개)
├── problems.md                 ← 진단된 문제점 및 개선 과제
├── DB_USAGE_GUIDE.md           ← 벡터 DB 사용 가이드 (테이블, 검색 전략)
├── ui/                         ← deep-agents-ui (git clone, .gitignore)
└── CLAUDE.md
```

## 빌드 & 실행

```bash
# --- 의존성 설치 ---
python3 -m venv .venv && source .venv/bin/activate
pip install -e .              # 프로덕션 의존성
pip install -e ".[dev]"       # + ruff, pytest, langgraph-cli

# --- 테스트 ---
python -m pytest tests/ -v    # 26개 전체 통과 확인

# --- LangGraph 서버 시작 (터미널 1) ---
langgraph dev --no-browser    # http://127.0.0.1:2024

# --- 프론트엔드 (터미널 2) ---
cd ui && yarn install && yarn dev   # http://localhost:3000
# 설정: Deployment URL = http://127.0.0.1:2024, Assistant ID = ifrs-agent

# --- 환경변수 (.env) ---
# ANTHROPIC_API_KEY=...       ← Claude API
# UPSTAGE_API_KEY=...         ← Upstage Solar Embedding
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

- `create_deep_agent()`는 `CompiledStateGraph`를 반환
- `langgraph.json`의 `"ifrs-agent": "./app/agent.py:agent"`로 서빙
- Checkpointer: `langgraph dev`가 in-memory checkpointer 자동 주입 (thread별 세션 유지)
- `app/agent.py`에서 `load_dotenv()` 호출하지 않음 — `langgraph.json`의 `"env": ".env"`가 처리

### 검색 도구 (`app/tools.py`) — 단계적 검색 전략

질문 성격에 따라 Agent가 적절한 도구를 선택:

| 도구 | 용도 | 호출 시점 |
|------|------|----------|
| `search_ifrs` | 권위 문단 벡터 검색 (top-5 기준서 통합) | 항상 (기본, 첫 번째로 호출) |
| `search_ifrs_examples` | IE 적용사례 검색 | 실무 처리 방법이 본문만으론 부족할 때 |
| `search_ifrs_rationale` | BC 결론도출근거 검색 | 기준 제정 배경·논거를 묻는 질문 |
| `get_standard_info` | 기준서 메타데이터 조회 | 기준서 기본 정보 확인 |

### 내부 검색 파이프라인

```
사용자 질문
  → embed_query()                     Upstage embedding-query
  → Step 1: _step1_identify_standard  standard_summaries top-5 (63행 벡터 검색)
  → 유사도 임계값 필터 (< 0.2 차단)
  → Step 2: _step2_search_multi       top-5 기준서 chunks 통합 검색 (UNNEST JOIN 단일 쿼리)
                                       authority <= base_authority 동적 필터
  → primary_id 판정                   Counter로 가장 많이 등장한 기준서 선택
  → 컨텍스트 포맷팅                    용어 정의 + 적용 문단 (기준서 ID 표시)
```

**핵심 설계 결정:**

- **복수 기준서 통합 검색**: Step 1에서 top-1만이 아닌 top-5 후보의 chunks를 한 번에 검색.
  유사도 차이가 작을 때 잘못된 기준서가 선택되는 문제 방지.
- **authority 동적 필터**: `authority = 1` 하드코딩 대신 `authority <= base_authority`.
  일반 기준서(1), 개념체계(3), 실무서(4) 모두 검색 가능.
- **유사도 임계값 0.2**: 회계 무관 질문을 차단. 관련 질문(0.29~0.47)은 통과.
- **반복 호출 제한**: 시스템 프롬프트에서 동일 도구 3회 반복 금지.

**캐시**: Step 2 결과를 `_step2_cache`에 TTL 60초, max 50개로 캐시 (thread-safe, TOCTOU 방지).

### DB 연결 (`app/db.py`)

- `psycopg_pool.ConnectionPool` 싱글턴 (thread-safe, double-checked locking)
- `get_connection()`: 컨텍스트 매니저 — `with get_connection() as conn:` 패턴으로 자동 반환
- pgvector 벡터 타입 자동 등록
- `DATABASE_URL` 미설정 시 `RuntimeError` (fail-fast)

### 임베딩 (`app/embedder.py`)

- Upstage Solar `embedding-query` 모델, 4096차원
- OpenAI 호환 API (`https://api.upstage.ai/v1`)
- retryable 에러만 catch (`APIConnectionError`, `APITimeoutError`, `RateLimitError`)
- thread-safe 싱글턴 클라이언트

### DB 스키마 (kifrs)

| 테이블 | 용도 | 비고 |
|--------|------|------|
| `standards` | 기준서 메타데이터 (63개) | `base_authority` 컬럼으로 authority 동적 필터 |
| `chunks` | 검색 대상 청크 (embedding vector(4096)), 14,762개 | `authority` 컬럼: 1/3/4 |
| `standard_summaries` | 기준서 식별용 요약 (embedding vector(4096)), 63개 | `scope_text`만 임베딩됨 |
| `footnotes` | 각주, 852개 | |
| `paragraph_links` | BC/IE → 본문 문단 참조 링크, 7,952개 | |

## 핵심 기술 스택 (2026.03 기준)

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `deepagents` | 0.4.12 | Agent 프레임워크 (LangGraph 기반) |
| `langgraph` | 1.1.3 | 상태 관리 + 그래프 런타임 |
| `langgraph-checkpoint-postgres` | 3.0.5 | 세션 메모리 (PostgreSQL) |
| `langchain-anthropic` | 1.4.0 | Claude 모델 통합 |
| `psycopg` | 3.3.3 | PostgreSQL 드라이버 |
| `pgvector` | 0.4.2 | 벡터 타입 지원 |
| `deep-agents-ui` | Next.js 16 | 프론트엔드 (Turbopack) |

## 코드 품질

- `ruff check app/` — 전체 통과
- `python -m pytest tests/` — 26개 테스트 전체 통과
- `[tool.ruff.lint]`: `E`, `F`, `I`, `N`, `UP`, `B`, `C4` 규칙 적용
- `app/prompts.py`는 E501 per-file-ignore (프롬프트 문자열 줄 길이 제외)
- 모든 SQL은 `%s` 파라미터화, `ANY(%s)` 배열 바인딩, `UNNEST` JOIN 사용
- `standard_id` 입력값은 정규식 `^K-IFRS\s+\d{4}$`로 검증

## K-IFRS 도메인 지식

### 권위 수준과 DB authority 매핑

| Level | 구성요소 | DB `authority` | DB `base_authority` |
|-------|---------|---------------|---------------------|
| 1 (Authoritative) | 기준서 본문, 적용지침, 정의, 경과규정, 해석서 | 1 | 1 |
| 3 (Framework) | 개념체계 | 3 | 3 |
| 4 (Non-authoritative) | 결론도출근거(BC), 적용사례(IE), 실무서 | 4 | 4 |

- `_step2_search_authoritative`: `WHERE authority <= base_authority` 동적 필터
- `_step2_search_multi`: `UNNEST JOIN`으로 기준서별 `base_authority` 적용

### K-IFRS 번호 체계

| | 구(舊) IASC (~2000) | 신(新) IASB (2001~) |
|---|---|---|
| **기준서** | 제10XX호 (IAS) | 제11XX호 (IFRS) |
| **해석서** | 제20XX호 (SIC) | 제21XX호 (IFRIC) |

### 특수 기준서

| standard_id | base_authority | 비고 |
|-------------|---------------|------|
| `재무보고 개념체계` | 3 | `authority <= 3` 필터 적용 |
| `실무서 2 중요성` | 4 | `authority <= 4` 필터 적용 |

### 한국 고유 요소

- "한" 접두어 문단 (예: 한82.1): 한국 고유 추가 요구사항 (carve-in)
- K-IFRS는 IFRS를 무수정 번역 채택, carve-out 없음

## 관련 프로젝트

- **`_IFRS_parsing`** (`/home/shin/Project/_IFRS_parsing/`): docx → 마크다운 → 벡터 DB 적재 파이프라인. 이 프로젝트의 DB를 사용함.
- **DB export**: `_IFRS_parsing/db_export/` — pg_dump 백업 파일
- **DB 사용 가이드**: `DB_USAGE_GUIDE.md` — 테이블 구조, 검색 전략, 임베딩 모델 상세
