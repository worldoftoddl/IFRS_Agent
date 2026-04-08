# Phase 2 회고: retrieval-distiller 서브에이전트 도입

## 개요

메인 Agent(Sonnet 4.6)에서 Level 1 검색을 분리하여 retrieval-distiller 서브에이전트(Haiku 4.5)로 위임하는 아키텍처 도입.

**기간**: 2026-04-05 ~ 2026-04-07

## 아키텍처 변경

### Before (단일 에이전트)
```
사용자 → 메인 Agent (Sonnet) → search_ifrs 직접 호출 → 답변
```

### After (서브에이전트 분리)
```
사용자 → 메인 Agent (Sonnet)
           ├─ task("retrieval-distiller") → Haiku가 검색·선별 → JSON 반환
           ├─ search_ifrs_examples (직접)
           ├─ search_ifrs_rationale (직접)
           └─ get_standard_info (직접)
```

### 설계 결정

| 결정 | 이유 |
|------|------|
| Haiku 4.5 선택 | 검색·선별은 추론 부담이 낮음. 비용/속도 최적화 |
| JSON 반환 형식 | 메인이 원문 인용할 수 있도록 original_text 보존 |
| 3개 도구 분리 | retrieve_ifrs(주력), lookup_paragraph(직접 조회), search_single_standard(단일 기준서) |
| BC/IE는 메인 유지 | 서브에이전트는 Level 1 전담. Level 4는 메인이 직접 조회 |

## 평가 결과

### E2E 평가 (36문항)

| 지표 | 값 |
|------|-----|
| **Std Accuracy** | 1.000 (36/36) |
| **Cited Recall** | 0.742 |
| **Avg Latency** | 45.74s |

### Retriever-only 대비

| 지표 | Retriever-only | Subagent E2E | 비고 |
|------|---------------|-------------|------|
| Std Accuracy | 0.889 | **1.000** | +11%p |
| Recall | 0.540 | **0.742** (Cited) | 지표 종류 다름 |
| Latency | ~수 초 | 45.74s | 서브에이전트 왕복 추가 |

- **Std Accuracy 1.000**: 모든 문항에서 정답 기준서를 인용
- **Cited Recall 0.742**: 검색 Recall(0.540)보다 높음 — 서브에이전트 선별 + Sonnet 추론이 시너지
- **Latency 증가**: 서브에이전트 왕복(Haiku 호출 + 도구 실행)으로 ~45초. 개선 여지 있음

## 발견한 문제와 해결

### 1. Haiku가 JSON을 마크다운 코드 블록으로 감쌈

**원인**: 프롬프트 내 JSON 예시가 코드 블록으로 감싸져 있어 모방.

**해결**: 코드 블록 제거 + 출력 규칙 강화 ("첫 글자 `{`", "마지막 `}`") + 프롬프트 맨 끝 재확인 섹션 추가.

### 2. 메인 에이전트의 task description이 과다 (486 토큰)

**원인**: deepagents 프레임워크가 "highly detailed task description"을 요구 → Sonnet이 충실히 따름.

**해결**: 메인 프롬프트에 "description에는 사용자의 원본 질문만 전달하세요" + 좋은 예/나쁜 예 추가.

### 3. Citation regex가 에이전트의 실제 인용 형식을 못 잡음

**원인**: 에이전트가 소수점 문단(4.1.2), B접두(B9), standalone 문단, 범위(42~43), 개념체계 약칭 등 다양한 형식 사용. 구 regex는 "K-IFRS XXXX 문단 YY"만 매칭.

**해결**: regex를 6가지 패턴으로 확장. standalone 문단은 가장 가까운 K-IFRS에 귀속. Cited Recall 0.281 → 0.742.

## 추가된 파일

| 파일 | 용도 |
|------|------|
| `app/subagent_prompts.py` | retrieval-distiller 시스템 프롬프트 |
| `app/subagent_tools.py` | 서브에이전트용 3개 도구 |
| `eval/evaluate_agent.py` | E2E 평가 모듈 + 확장 citation regex |
| `agent_evaluation.ipynb` | 평가 + 자유 질의 노트북 |
| `tests/test_subagent_integration.py` | 서브에이전트 통합 테스트 |
| `tests/test_subagent_tools.py` | 서브에이전트 도구 테스트 |
| `tests/test_agent_evaluation.py` | 평가 모듈 테스트 (14개 citation 패턴) |

## 향후 과제

- **Latency 개선**: 현재 ~46초. 서브에이전트 도구 호출 횟수 최적화 또는 캐싱 검토
- **Cited Recall 0.742 → 0.85+**: 서브에이전트가 더 정확한 문단을 선별하도록 프롬프트 튜닝
- **UI 구현**: QnA 채팅 인터페이스 + Vercel 배포
