# DB 품질 리포트 대응: IAS 본문 누락 수정 완료

**작성일**: 2026-03-25
**대상**: `DB_QUALITY_REPORT.md` (IAS 계열 기준서 본문 누락)
**커밋**: `d400a4a` (파서 수정) + `c05c20c` (DB 재적재)

---

## 1. 근본 원인

리포트에서 추정한 **가능성 2 (마크다운 → 청크 파싱 실패)**가 정확했다.

### 문제 발생 경로

```
Stage 1 출력 (마크다운):

  ## 본 문                          → component: main ✅
  <!-- component: main | authority: 1 -->
    문단 1~7 (목적, 적용범위)

  ## 용어의 정의                    → component: definitions
  <!-- component: definitions | authority: 1 -->
    문단 8~17 (정의 내용)
    ### 환산방법의 요약              ← 서브섹션이지만 ## 없이 ### 만 나옴
    문단 20~22 (외화거래 최초 인식)  ← 실제 본문인데 definitions에 갇힘
    ### 기능통화 환산
    문단 23~37                      ← 핵심 내용이 전부 definitions
    ...

  ## 시행일과 경과규정              → component: transition
```

**Stage 1 (docx → 마크다운)**은 정상. 마크다운 파일에 문단 23, 28, 39 등이 모두 존재.

**Stage 2 파서 (`ingester/md_parser.py`)**가 문제:
- `## 용어의 정의` → `current_component = "definitions"` 진입
- 이후 `### 서브섹션`이 나와도 **component가 definitions에 고정**
- `## 시행일과 경과규정`이 나올 때까지 모든 문단이 definitions로 분류
- definitions 청크는 검색 대상에서 제외 (`summary.definitions_text`로 통합) → **본문 전체 누락**

### IAS vs IFRS 구조 차이

| | IFRS 계열 (11XX) | IAS 계열 (10XX) |
|---|---|---|
| 편제 | `## 본 문` 하나가 적용지침 전까지 | 중간에 `## 용어의 정의`가 끼어듦 |
| 정의 이후 | 별도 `## 본 문` 헤더로 복귀 | **복귀 헤더 없이** `###`로 바로 이어짐 |
| 영향 | 없음 | 8개 기준서 본문 전체 누락 |

이것은 IAS (IASC 시절 제정)와 IFRS (IASB 제정)의 문서 편제 철학이 다르기 때문. CLAUDE.md에도 "IAS와 IFRS는 문서 구조가 상당히 다를 수 있어 파서 설계 시 감안 필요"로 기록되어 있었으나, Stage 2 파서에서 이 차이를 처리하지 못했음.

---

## 2. 수정 내용

### 파이프라인 수정: `ingester/md_parser.py` (1줄 로직 추가)

```python
# 서브섹션 헤더 (### level 3) 처리부
if stripped.startswith("### "):
    _flush_chunk()
    current_section_title = stripped[4:].strip()
    # IAS 계열: "용어의 정의" 이후 서브섹션이 나오면 본문 복귀
    if current_component == "definitions":
        current_component = "main"
        current_authority = standard.base_authority
    continue
```

**로직**: `definitions` 컴포넌트 내에서 `### 서브섹션`을 만나면 `main`으로 복원.

**근거**: IAS 기준서의 정의 섹션은 `###` 없이 연속 텍스트로 구성됨. `###`가 등장하면 그것은 정의가 아닌 본문의 소제목.

**영향 범위**: `definitions` → `main` 전환만 추가. 다른 component(bc, ie, transition)에는 영향 없음.

---

## 3. 수정 결과

### main 문단 수 비교

| 기준서 | 수정 전 | 수정 후 | 복원된 문단 수 |
|--------|---------|---------|--------------|
| K-IFRS 1001 (재무제표 표시) | 7 | **176** | +169 |
| K-IFRS 1038 (무형자산) | 8 | **126** | +118 |
| K-IFRS 1039 (금융상품) | 3 | **63** | +60 |
| K-IFRS 1021 (환율변동) | 8 | **58** | +50 |
| K-IFRS 1008 (회계정책) | 5 | **56** | +51 |
| K-IFRS 1028 (관계기업) | 3 | **48** | +45 |
| K-IFRS 1041 (농림어업) | 6 | **47** | +41 |
| K-IFRS 1027 (별도재무제표) | 9 | **21** | +12 |
| **합계** | **49** | **595** | **+546** |

### 전체 DB 통계

| 항목 | 수정 전 | 수정 후 |
|------|---------|---------|
| 총 검색 청크 | 14,762 | **16,616** |
| main 청크 | 3,902 | **5,756** |
| 임베딩 완료 | 14,762 | **16,616** (100%) |
| 실패 | 0 | 0 |

---

## 4. 테스트

TDD로 회귀 테스트 작성: `tests/test_definitions_main_restore.py`

| 테스트 | 검증 내용 | 결과 |
|--------|----------|------|
| `test_main_chunk_count` (8개) | 각 기준서의 main 청크 최소 수 | 17 passed |
| `test_critical_paragraphs_in_main` (8개) | 핵심 문단(23, 28, 39 등)이 main에 있는지 | 7 passed, 1 skipped |
| `test_1021_para23_not_in_definitions` | 문단 23이 definitions가 아닌 main | passed |
| `test_definitions_only_contains_actual_definitions` | definitions에 본문이 섞이지 않는지 | passed |

---

## 5. 리포트에서 제안한 수정 방안 대응

| 리포트 제안 | 대응 | 상태 |
|------------|------|------|
| Agent 프롬프트에 DB 한계 안내 규칙 | 불필요 (데이터 복원됨) | 해소 |
| 마크다운 파일 점검 | 마크다운은 정상이었음 (Stage 2 파서 문제) | 확인 |
| `converter/docx_parser.py` 수정 | 불필요 (Stage 1은 정상) | 해소 |
| 해당 기준서 재파싱 → 재적재 | **완료** (전체 63개 재적재) | 완료 |
| 검증 쿼리 실행 | main < 10인 기준서: 개념체계/실무서/SIC만 (정상) | 확인 |

---

## 6. 재발 방지

### 이미 적용

- `tests/test_definitions_main_restore.py`: 8개 기준서 main 문단 수 회귀 테스트
- 새 기준서 추가 시 `python -m pytest tests/` 실행으로 동일 이슈 방지

### 향후 권장

- `ingest.py` 실행 후 자동 검증 쿼리 추가:
  ```sql
  SELECT standard_id, count(*) FROM chunks
  WHERE component = 'main' AND authority = 1
  GROUP BY standard_id HAVING count(*) < 10;
  ```
  결과가 개념체계/실무서/SIC 이외의 기준서를 포함하면 경고

- Stage 2 파서에 `component` 전환 로그 추가 (디버깅용):
  ```
  [K-IFRS 1021] definitions → main (### 환산방법의 요약)
  ```
