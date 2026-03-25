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
│   ├── tools.py                ← 4개 도구: search_ifrs, search_ifrs_examples,
│   │                              search_ifrs_rationale, get_standard_info
│   ├── db.py                   ← psycopg ConnectionPool + pgvector (thread-safe 싱글턴)
│   ├── embedder.py             ← Upstage embedding-query 래퍼 (thread-safe 싱글턴)
│   └── prompts.py              ← K-IFRS 전문가 시스템 프롬프트
├── ui/                         ← deep-agents-ui (git clone, .gitignore)
└── CLAUDE.md
```

## 빌드 & 실행

```bash
# --- 의존성 설치 ---
python3 -m venv .venv && source .venv/bin/activate
pip install -e .              # 프로덕션 의존성
pip install -e ".[dev]"       # + ruff, pytest, langgraph-cli

# --- LangGraph 서버 시작 ---
langgraph dev --no-browser    # http://127.0.0.1:2024 에서 서빙

# --- 프론트엔드 (deep-agents-ui) ---
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
| `search_ifrs` | Level 1 기준서 본문/적용지침 검색 | 항상 (기본, 첫 번째로 호출) |
| `search_ifrs_examples` | IE 적용사례 검색 | 실무 처리 방법이 본문만으론 부족할 때 |
| `search_ifrs_rationale` | BC 결론도출근거 검색 | 기준 제정 배경·논거를 묻는 질문 |
| `get_standard_info` | 기준서 메타데이터 조회 | 기준서 기본 정보 확인 |

**내부 파이프라인:**

| Step | 기능 | 테이블 |
|------|------|--------|
| 1 | 쿼리 → 기준서 식별 | `standard_summaries` (cosine similarity) |
| 2 | 기준서 내 Level 1 문단 벡터 검색 | `chunks` (authority=1) |
| 3 | IE 적용사례 링크 조회 | `paragraph_links` (source_component='ie') → `chunks` |
| 4 | BC 결론도출근거 링크 조회 | `paragraph_links` (source_component='bc') → `chunks` |

**캐시**: Step 2 결과(임베딩 + 문단 번호)를 `_step2_cache`에 TTL 60초, max 50개로 캐시.
`search_ifrs` 실행 후 `search_ifrs_examples`/`search_ifrs_rationale` 호출 시 임베딩 API 재호출 없이 캐시 히트.

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

| 테이블 | 용도 |
|--------|------|
| `standards` | 기준서 메타데이터 (63개) |
| `chunks` | 검색 대상 청크 (embedding vector(4096)), 14,762개 |
| `standard_summaries` | 기준서 식별용 요약 (embedding vector(4096)), 63개 |
| `footnotes` | 각주 |
| `paragraph_links` | BC/IE → 본문 문단 참조 링크, 7,952개 |

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
- `[tool.ruff.lint]`: `E`, `F`, `I`, `N`, `UP`, `B`, `C4` 규칙 적용
- `app/prompts.py`는 E501 per-file-ignore (프롬프트 문자열 줄 길이 제외)
- 모든 SQL은 `%s` 파라미터화 또는 `ANY(%s)` 배열 바인딩 사용
- `standard_id` 입력값은 정규식 `^K-IFRS\s+\d{4}$`로 검증

## K-IFRS 도메인 지식

### 권위 수준 5단계

| Level | 구성요소 | 검색 우선순위 |
|-------|---------|-------------|
| 1 (Authoritative) | 기준서 본문, 부록A(정의), 부록B(적용지침), 경과규정, 해석서 | 최상위 |
| 2 (Quasi-authoritative) | IFRIC 안건결정 | 상위 |
| 3 (Framework) | 개념체계 | 중위 |
| 4 (Non-authoritative) | 결론도출근거(BC), 적용사례(IE) | 하위 |
| 5 (External) | US GAAP, Big 4 출판물 | 최하위 |

Agent 답변 시 Level 1 문단을 우선 인용하고, Level 4는 보조 참고로만 사용해야 한다.
BC/IE는 기준서의 일부를 구성하지 않으므로 본문과 충돌 시 본문이 우선한다.
현재 DB에는 Level 1, 4만 포함. Level 2(IFRIC 안건결정), Level 3(개념체계)는 미포함.

### K-IFRS 번호 체계

| | 구(舊) IASC (~2000) | 신(新) IASB (2001~) |
|---|---|---|
| **기준서** | 제10XX호 (IAS) | 제11XX호 (IFRS) |
| **해석서** | 제20XX호 (SIC) | 제21XX호 (IFRIC) |

### 한국 고유 요소

- "한" 접두어 문단 (예: 한82.1): 한국 고유 추가 요구사항 (carve-in)
- K-IFRS는 IFRS를 무수정 번역 채택, carve-out 없음

## 관련 프로젝트

- **`_IFRS_parsing`** (`/home/shin/Project/_IFRS_parsing/`): docx → 마크다운 → 벡터 DB 적재 파이프라인. 이 프로젝트의 DB를 사용함.
- **DB export**: `_IFRS_parsing/db_export/` — pg_dump 백업 파일
