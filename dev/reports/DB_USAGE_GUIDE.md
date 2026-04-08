# K-IFRS 벡터 DB 사용 가이드

이 문서는 K-IFRS 벡터 DB를 **검색 파이프라인에서 사용하는 방법**을 설명한다. DB 구축(청킹/적재)은 이미 완료되어 있으며, 이 가이드는 DB를 **읽고 검색하는 쪽**을 위한 것이다.

---

## 1. DB 연결

```python
import psycopg
from pgvector.psycopg import register_vector

conn = psycopg.connect("dbname=kifrs", autocommit=True)
register_vector(conn)
```

PostgreSQL은 WSL 로컬에서 실행 중 (`dbname=kifrs`, peer 인증).

---

## 2. 테이블 구조

### 2.1 `standards` — 기준서 메타데이터 (63행)

| 컬럼 | 설명 |
|------|------|
| `standard_id` (PK) | `"K-IFRS 1115"`, `"재무보고 개념체계"` |
| `standard_number` | `"1115"` (개념체계는 NULL) |
| `title` | `"고객과의 계약에서 생기는 수익"` |
| `standard_type` | `"standard"` / `"interpretation"` / `"framework"` / `"practice_statement"` |
| `standard_family` | `"IAS"` / `"IFRS"` / `"SIC"` / `"IFRIC"` / `"CF"` / `"PS"` |
| `original_number` | `"IFRS 15"`, `"IAS 1"` (IASB 원본 번호) |
| `base_authority` | 1=기준서/해석서, 3=개념체계, 4=실무서 |
| `total_chunks` | 해당 기준서의 검색 대상 청크 수 |

### 2.2 `chunks` — 검색 대상 청크 (14,762행, 전부 임베딩 완료)

| 컬럼 | 설명 |
|------|------|
| `chunk_id` (PK) | `"KIFRS1115-main-9"` (기준서-컴포넌트-문단번호) |
| `standard_id` (FK) | `"K-IFRS 1115"` |
| `para_number` | `"9"`, `"B34"`, `"BC12A"`, `"한2.1"`, NULL(번호 없음) |
| `component` | `"main"` / `"ag"` / `"bc"` / `"ie"` / `"transition"` |
| `section_title` | `"인식"`, `"계약을 식별함"` (가장 가까운 ### 제목) |
| `authority` | 1=의무(Authoritative), 3=개념체계, 4=비권위(Non-authoritative) |
| `content_text` | 임베딩용 plain text (마크다운 서식 제거) |
| `content_markdown` | LLM에 보여줄 원본 마크다운 (**bold**, *italic*, 호/목 포함) |
| `embedding` | vector(4096) — Upstage `embedding-passage` |

### 2.3 `standard_summaries` — 기준서 요약 + 정의 (63행)

| 컬럼 | 설명 |
|------|------|
| `standard_id` (PK) | `"K-IFRS 1115"` |
| `title` | `"고객과의 계약에서 생기는 수익"` |
| `scope_text` | 목적+적용범위 plain text **(임베딩됨)** |
| `scope_markdown` | 목적+적용범위 원본 마크다운 |
| `definitions_text` | 용어 정의 전체 plain text **(임베딩 안 됨, LLM 컨텍스트용)** |
| `definitions_markdown` | 용어 정의 원본 마크다운 |
| `embedding` | vector(4096) — `scope_text`의 임베딩 |

### 2.4 `paragraph_links` — BC/IE → 본문 참조 (7,952행)

| 컬럼 | 설명 |
|------|------|
| `standard_id` | `"K-IFRS 1115"` |
| `source_chunk_id` | BC/IE 청크 ID (`"KIFRS1115-bc-BC42"`) |
| `source_component` | `"bc"` 또는 `"ie"` |
| `source_para` | `"BC42"`, `"IE2"` |
| `target_para_start` | 참조 대상 본문 문단 시작 (`"9"`) |
| `target_para_end` | 참조 대상 본문 문단 끝 (`"16"`, 단일이면 NULL) |
| `link_type` | `"section_heading"` (제목에서 추출) / `"body_reference"` (본문에서 추출) |

### 2.5 `footnotes` — 각주 (852행)

| 컬럼 | 설명 |
|------|------|
| `standard_id` | `"K-IFRS 1001"` |
| `footnote_number` | 1, 2, 3... (기준서 내 번호) |
| `content` | 각주 내용 |

---

## 3. 임베딩 모델 (중요)

Upstage Solar Embedding은 **비대칭(asymmetric)** 모델이다. 문서와 쿼리에 **다른 모델**을 사용해야 한다.

| 용도 | 모델명 | 사용 시점 |
|------|--------|----------|
| 문서/청크 임베딩 | `embedding-passage` | DB 적재 시 (이미 완료) |
| **검색 쿼리 임베딩** | **`embedding-query`** | **검색 시 반드시 이 모델 사용** |

```python
from ingester.embedder import Embedder
embedder = Embedder()

# 검색 시 — 반드시 embed_query 사용
query_emb = embedder.embed_query("수행의무 판단 기준")

# 문서 적재 시 — embed_single 또는 embed_batch
doc_emb = embedder.embed_single("문서 텍스트")
```

---

## 4. 검색 파이프라인 (4단계)

이 DB는 CPA(공인회계사)의 실제 회계처리 워크플로우에 맞춰 설계되었다:

```
사용자 질문: "고객과의 계약에서 수행의무를 어떻게 판단하는가?"

Step 1: 어떤 기준서에 해당하는지 찾기        → K-IFRS 1115
Step 2: 그 기준서의 본문(Level 1)에서 검색    → 문단 22, B34 등
Step 3: 실무 예시가 필요하면 IE 참조          → IE2 (문단 9~16 관련 사례)
Step 4: 왜 그런 회계처리인지 설명이 필요하면 BC 참조 → BC42 (문단 9 근거)
```

### Step 1: 기준서 식별

`standard_summaries` 테이블의 `embedding`을 검색한다. **63행**뿐이므로 매우 빠르다.

```sql
SELECT standard_id, title,
       1 - (embedding <=> :query_embedding) AS similarity
FROM standard_summaries
ORDER BY embedding <=> :query_embedding
LIMIT 5;
```

**주의**: `scope_text`만 임베딩되어 있다. `definitions_text`는 임베딩되지 않았다.

### Step 2: Level 1 문단 검색 (핵심)

**반드시 `authority = 1`로 필터링**하여 본문과 적용지침만 검색한다. BC/IE를 섞으면 안 된다.

```sql
SELECT chunk_id, para_number, component, section_title,
       content_markdown,
       1 - (embedding <=> :query_embedding) AS similarity
FROM chunks
WHERE standard_id = :standard_id
  AND authority = 1
ORDER BY embedding <=> :query_embedding
LIMIT 10;
```

**왜 Level 1만 검색하는가?**
- `authority = 1` (main, ag, definitions, transition): **기준서의 일부를 구성하는** 의무적 내용
- `authority = 4` (bc, ie): **기준서의 일부를 구성하지 않는** 참고 자료
- BC/IE를 Level 1과 섞어 검색하면, 비권위적 참고 자료가 본문과 동등하게 취급되어 답변 정확도가 떨어진다
- BC/IE는 Step 3-4에서 **별도 경로**로 제공해야 한다

**결과 그룹핑** (main → ag 순서):
```python
COMPONENT_ORDER = {"main": 0, "definitions": 1, "ag": 2, "transition": 3}
results.sort(key=lambda r: (COMPONENT_ORDER.get(r.component, 99), -r.similarity))
```

### Step 3: IE 적용사례 (조건부)

사용자가 "실무적인 예시를 보여줘"라고 요청할 때 실행. **벡터 검색이 아닌 `paragraph_links`** 테이블을 사용한다.

```sql
-- Step 2에서 찾은 본문 문단번호 = ['9', '10', '22']
SELECT DISTINCT c.chunk_id, c.para_number, c.section_title,
       c.content_markdown
FROM paragraph_links pl
JOIN chunks c ON c.chunk_id = pl.source_chunk_id
WHERE pl.standard_id = :standard_id
  AND pl.source_component = 'ie'
  AND pl.target_para_start IN ('9', '10', '22')
LIMIT 5;
```

**왜 벡터 검색 대신 링크를 사용하는가?**
- IE/BC 문단은 "문단 9~16의 요구사항에 대하여 설명한다"처럼 본문 문단을 명시적으로 참조한다
- 이 참조를 `paragraph_links` 테이블에 미리 추출해놓았다 (7,952건)
- 벡터 검색보다 정확하고, 본문 문단과의 관계가 명확하다
- 링크가 없는 경우에만 벡터 검색으로 폴백한다

### Step 4: BC 결론도출근거 (조건부)

사용자가 "왜 이런 회계처리를 하는가?"라고 질문할 때 실행. Step 3과 동일 방식.

```sql
SELECT DISTINCT c.chunk_id, c.para_number, c.section_title,
       c.content_markdown
FROM paragraph_links pl
JOIN chunks c ON c.chunk_id = pl.source_chunk_id
WHERE pl.standard_id = :standard_id
  AND pl.source_component = 'bc'
  AND pl.target_para_start IN ('9', '10', '22')
LIMIT 5;
```

---

## 5. LLM 컨텍스트 구성

4단계 결과를 LLM에 보낼 때의 포맷:

```markdown
# K-IFRS 1115 고객과의 계약에서 생기는 수익
사용자 질문: 수행의무 판단 기준은?

## 용어 정의 [참조]
{standard_summaries.definitions_text — 항상 포함}

## 적용 문단 [Authoritative, Level 1]

### 본문
**문단 22** (수행의무를 식별함)
{content_markdown}

### 적용지침
**문단 B34** (구별되는 재화나 용역)
{content_markdown}

## 적용사례 [Non-authoritative, Level 4]
**IE2** (사례 1~4: 계약 식별에 관한 문단 9~16의 요구사항)
{content_markdown}

## 결론도출근거 [Non-authoritative, Level 4]
*주의: 결론도출근거는 기준서의 일부를 구성하지 않습니다. 본문과 충돌 시 본문이 우선합니다.*
**BC42** (문단 9 관련)
{content_markdown}
```

### 핵심 규칙

1. **정의(`definitions_text`)는 벡터 검색하지 말고 컨텍스트에 직접 주입한다**
   - 정의는 임베딩되어 있지 않다
   - 기준서가 결정되면 해당 기준서의 `standard_summaries.definitions_text`를 통째로 넣는다
   - 기준서당 보통 10~30개 용어, 몇 KB 수준이라 컨텍스트 부담 없다

2. **권위 수준 라벨을 반드시 표시한다**
   - LLM이 "[Authoritative]"와 "[Non-authoritative]"를 구분하여 답변 생성해야 한다
   - BC와 본문이 충돌하면 본문이 우선한다는 점을 명시한다

3. **BC/IE는 Step 2 결과와 별도 섹션으로 제공한다**
   - Step 2 결과(본문+AG)와 Step 3-4 결과(IE+BC)를 하나로 섞지 않는다

---

## 6. component 설명

| component | 한국어 | 영문 | authority | 검색 대상? |
|-----------|--------|------|-----------|-----------|
| `main` | 본문 | Standard Text | 1 | ✅ Step 2 |
| `ag` | 적용지침 (부록 B) | Application Guidance | 1 | ✅ Step 2 |
| `transition` | 경과규정 (부록 C) | Transition | 1 | ✅ Step 2 |
| `definitions` | 용어의 정의 (부록 A) | Defined Terms | — | ❌ summary에 통합 |
| `bc` | 결론도출근거 | Basis for Conclusions | 4 | ✅ Step 4 (링크) |
| `ie` | 적용사례 | Illustrative Examples | 4 | ✅ Step 3 (링크) |

**주의**: 일부 기준서에서 `ie` 문단(IG1, IG2...)이 `ag` component로 잡혀있을 수 있다. `para_number`가 `IE` 또는 `IG`로 시작하면 실질적으로 적용사례(Level 4)이다.

---

## 7. 특수 기준서

| standard_id | base_authority | 설명 |
|-------------|---------------|------|
| `재무보고 개념체계` | 3 | 개념체계. 기준서보다 하위 권위 |
| `경영진설명서 개념체계` | 3 | 개념체계 |
| `실무서 2 중요성` | 4 | 실무서. 의무사항 아님 |

이들은 `authority = 3` 또는 `4`로 태깅되어 있으므로, `authority = 1` 필터에서 자동 제외된다.

---

## 8. DB 통계 (현재)

```
standards:          63
chunks:             14,762 (전부 임베딩 완료)
standard_summaries: 63 (전부 임베딩 완료)
paragraph_links:    7,952 (BC 6,613 + IE 1,339)
footnotes:          852

가장 큰 기준서: K-IFRS 1109 (2,317 청크), K-IFRS 1115 (1,278 청크)
가장 작은 기준서: SIC 해석서 (~10-20 청크)
```

---

## 9. 벡터 인덱스 (현재 없음)

pgvector 0.6은 HNSW/IVFFlat 모두 **2,000차원 제한**이 있어, 4,096차원 임베딩에는 인덱스를 생성하지 않았다. `WHERE standard_id = X`로 필터하면 기준서당 평균 ~234행만 스캔하므로 exact search로도 충분히 빠르다.

pgvector 0.7+ 업그레이드 시 HNSW 인덱스 생성 가능:
```sql
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

---

## 10. 코드 참조

| 파일 | 설명 |
|------|------|
| `ingester/embedder.py` | `Embedder` 클래스 — `embed_query()` / `embed_single()` / `embed_batch()` |
| `ingester/config.py` | DB URL, API 키 등 설정 (`Config.from_env()`) |
| `schema.sql` | 전체 DDL |
| `search_test.ipynb` | 4단계 검색 파이프라인 대화형 테스트 노트북 |
| `how_to_read_IFRS.md` | IFRS 권위 수준 5단계, IAS 8 해석 위계 상세 참조 |
