# K-IFRS Agent 기능 확장 로드맵

## 현재 상태 (2026-04-08)

핵심 기능 완성: Dense 검색 + Cohere Reranker + retrieval-distiller 서브에이전트 + 챗봇 UI
- Std Accuracy: 100% (36/36)
- Cited Recall: 74.2%
- 메인: Claude Sonnet 4.6 / 서브: Claude Haiku 4.5

### 설계 원칙

**도구 vs 스킬 구분**: LLM이 자체적으로 할 수 없는 것만 도구로 만든다.
- 정확한 수치 계산 (PV, EIR, 상각표) → **도구** (Python 계산)
- 기준서 비교, 분개 작성, 공시 검증 → **스킬** (프롬프팅 패턴, 이미 검색+추론 가능)

---

## Phase 0: 컨텍스트 압축 (난이도: 낮음)

### 목표
긴 대화 시 토큰 자동 절약 — deepagents 내장 `SummarizationMiddleware` 튜닝

### 배경
`create_deep_agent()`가 SummarizationMiddleware를 기본 스택에 자동 포함.
K-IFRS 도메인에 맞게 trigger/keep 임계값을 조정.

### 할 일
1. `deepagents/graph.py`에서 기본 활성화 여부 및 기본값 확인
2. `app/agent.py`에 커스텀 설정 추가:
   - `trigger=("tokens", 80000)` — 80k 토큰 초과 시 트리거
   - `keep=("tokens", 4000)` — 최근 4k 토큰 유지
   - 요약 모델: Haiku (비용 절감)

### 변경 파일
- `app/agent.py` (1개)

### 검증
- 긴 대화(10+ 턴) 후 토큰 사용량 확인
- LangSmith에서 요약 이벤트 발생 여부 확인
- 기준서 ID/문단번호가 요약 후에도 보존되는지 확인

---

## Phase 1: Skills — 회계 작업 프리셋 7개 (난이도: 중간)

### 목표
반복되는 회계 분석 패턴을 SKILL.md로 정의.
deepagents `SkillsMiddleware`가 시스템 프롬프트에 자동 주입.
frontmatter(name, description)만 기본 로드 → 에이전트가 필요 시 전체 읽기.

### 인프라 설정
```python
# app/agent.py
from deepagents.backends.filesystem import FilesystemBackend

agent = create_deep_agent(
    ...
    backend=FilesystemBackend(root_dir="./"),
    skills=["./app/skills/"],
)
```

### 디렉토리 구조
```
app/skills/
├── lease-classification/SKILL.md        ← 리스 분류 (K-IFRS 1116)
├── revenue-recognition/SKILL.md         ← 수익 인식 5단계 (K-IFRS 1115)
├── provision-assessment/SKILL.md        ← 충당부채 판단 (K-IFRS 1037)
├── impairment-testing/SKILL.md          ← 손상 검사 (K-IFRS 1036)
├── financial-instruments/SKILL.md       ← 금융상품 분류 (K-IFRS 1109)
├── standard-comparison/SKILL.md         ← 기준서 비교 프레임워크
└── journal-entry/SKILL.md               ← 분개 생성/검증 절차
```

### 스킬 목록

| 스킬 | K-IFRS | 트리거 |
|------|--------|--------|
| lease-classification | 1116 | 리스 분류, 금융리스/운용리스 구분 |
| revenue-recognition | 1115 | 수익 인식 5단계, 수행의무 |
| provision-assessment | 1037 | 충당부채 인식/측정 판단 |
| impairment-testing | 1036 | 자산 손상 검사 절차 |
| financial-instruments | 1109 | 금융상품 분류/측정 의사결정 트리 |
| standard-comparison | - | 두 기준서 회계처리 비교 요청 시 |
| journal-entry | - | 분개 생성/검증 요청 시 |

### 변경 파일
- `app/skills/*/SKILL.md` (7개 신규)
- `app/agent.py` (수정 — backend, skills 파라미터)
- `pyproject.toml` (필요 시 deepagents 버전 범프)

### 검증
- "리스 분류 기준이 뭐야?" → 5가지 기준 체계적 답변
- "K-IFRS 1037과 1109의 금융보증계약 차이" → 비교 프레임워크 적용
- "건물 임차 보증금 분개" → 차변/대변 절차 적용

---

## Phase 2: 재무 계산 도구 3종 (난이도: 높음)

### 신규 파일: `app/accounting_tools.py`

순수 Python, 외부 의존성 없음 (Newton-Raphson으로 EIR 직접 구현).

| 도구 | 용도 | 활용 기준서 |
|------|------|-----------|
| `calculate_present_value` | 현금흐름 현재가치 | 1037 충당부채, 1116 리스, 1109 금융상품 |
| `calculate_effective_interest_rate` | 유효이자율 | 1109 상각후원가 측정 |
| `build_amortization_schedule` | 상각표 생성 | 1116 리스부채, 1109 사채 |

### 구현 노트
- PV: `sum(cf / (1 + r)**t for t, cf in enumerate(cash_flows, 1))`
- EIR: Newton-Raphson 반복 (scipy 불필요)
- 상각표: 이자 = 잔액 * 이자율, 원금상환 = 납부액 - 이자
- 모두 **마크다운 테이블** 반환 (챗봇 UI 렌더링)
- 입력 검증: 음수 이자율, 빈 현금흐름, 비수렴

### 변경 파일
- `app/accounting_tools.py` (신규)
- `app/agent.py` (수정 — MAIN_TOOLS 확장)
- `app/prompts.py` (수정 — 계산 도구 사용 지침 추가)
- `dev/tests/test_accounting_tools.py` (신규 — TDD)

### 검증
- "5년간 매년 100만원, 할인율 10%의 현재가치는?" → 3,790,787원
- "액면가 1억, 표시이자율 5%, 발행가 9500만의 유효이자율은?"
- "원금 1억, 이자율 5%, 5년 균등상환 상각표"

---

## 전체 변경 파일 요약

| Phase | 파일 | 변경 유형 |
|-------|------|----------|
| 0 | `app/agent.py` | 수정 (SummarizationMiddleware 설정) |
| 1 | `app/skills/*/SKILL.md` (7개) | 신규 |
| 1 | `app/agent.py` | 수정 (backend, skills 파라미터) |
| 1 | `pyproject.toml` | 수정 (deepagents 버전, 필요 시) |
| 2 | `app/accounting_tools.py` | 신규 |
| 2 | `app/agent.py` | 수정 (MAIN_TOOLS 확장) |
| 2 | `app/prompts.py` | 수정 (계산 도구 지침) |
| 2 | `dev/tests/test_accounting_tools.py` | 신규 |

각 Phase는 독립 배포 가능. Phase 2는 TDD (테스트 먼저 작성).

---

## 리스크

| 리스크 | 대응 |
|--------|------|
| deepagents API 불일치 (skills/middleware) | 설치된 패키지 소스 확인 후 코딩; 버전 고정 |
| 도구 수 증가 → 에이전트 혼란 | 계산 도구 3개만 추가; 프롬프트에 명확한 사용 규칙 |
| Skills가 시스템 프롬프트를 길게 만듦 | frontmatter만 기본 로드; 에이전트가 필요 시 전체 읽기 |
| 요약 시 회계 맥락 손실 | Haiku로 요약; 기준서 ID 보존 테스트 |
| FilesystemBackend + LangGraph 서버 호환성 | langgraph dev에서 테스트; 문제 시 InMemoryStore 대체 |
