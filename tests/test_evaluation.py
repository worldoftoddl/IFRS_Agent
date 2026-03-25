"""Golden dataset 평가 프레임워크 테스트.

evaluate 모듈이 golden dataset을 로드하고,
검색 파이프라인을 실행하여 Recall@K, MRR, Standard Accuracy를 산출하는지 검증.
"""

import json
import pytest
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

GOLDEN_PATH = Path(__file__).parent.parent / "eval" / "golden_dataset.json"


class TestGoldenDataset:
    """Golden dataset 파일 검증."""

    def test_golden_file_exists(self):
        """golden_dataset.json 파일이 존재해야 한다."""
        assert GOLDEN_PATH.exists(), f"{GOLDEN_PATH} 파일이 없음"

    def test_golden_valid_json(self):
        """유효한 JSON이어야 한다."""
        data = json.loads(GOLDEN_PATH.read_text())
        assert isinstance(data, list)
        assert len(data) >= 15, f"최소 15문항 필요, 현재 {len(data)}문항"

    def test_golden_schema(self):
        """각 항목에 필수 필드가 있어야 한다."""
        data = json.loads(GOLDEN_PATH.read_text())
        required = {"id", "query", "expected_standard", "expected_paragraphs", "category"}
        for item in data:
            missing = required - set(item.keys())
            assert not missing, f"{item.get('id', '?')}: 누락 필드 {missing}"
            assert isinstance(item["expected_paragraphs"], list)
            assert len(item["expected_paragraphs"]) > 0

    def test_golden_ids_unique(self):
        """ID가 고유해야 한다."""
        data = json.loads(GOLDEN_PATH.read_text())
        ids = [item["id"] for item in data]
        assert len(ids) == len(set(ids)), "중복 ID 존재"


class TestEvaluateModule:
    """evaluate 모듈 기능 검증."""

    def test_import_evaluate(self):
        """evaluate 모듈을 임포트할 수 있어야 한다."""
        from eval.evaluate import load_golden, run_evaluation, compute_metrics
        assert callable(load_golden)
        assert callable(run_evaluation)
        assert callable(compute_metrics)

    def test_load_golden(self):
        """load_golden()이 golden dataset을 로드해야 한다."""
        from eval.evaluate import load_golden
        data = load_golden()
        assert len(data) >= 15

    def test_compute_metrics_perfect(self):
        """모든 문단이 찾아진 경우 recall=1.0, mrr=1.0이어야 한다."""
        from eval.evaluate import compute_metrics

        result = {
            "expected_paragraphs": ["14", "15"],
            "found_paragraphs": ["14", "15", "16"],
            "first_correct_rank": 1,
            "expected_standard": "K-IFRS 1037",
            "primary_standard": "K-IFRS 1037",
        }
        metrics = compute_metrics(result)
        assert metrics["recall"] == 1.0
        assert metrics["mrr"] == 1.0
        assert metrics["std_accuracy"] == 1

    def test_compute_metrics_partial(self):
        """일부 문단만 찾아진 경우 recall < 1.0이어야 한다."""
        from eval.evaluate import compute_metrics

        result = {
            "expected_paragraphs": ["14", "15", "16"],
            "found_paragraphs": ["14"],
            "first_correct_rank": 3,
            "expected_standard": "K-IFRS 1037",
            "primary_standard": "K-IFRS 1037",
        }
        metrics = compute_metrics(result)
        assert abs(metrics["recall"] - 1 / 3) < 0.01
        assert abs(metrics["mrr"] - 1 / 3) < 0.01
        assert metrics["std_accuracy"] == 1

    def test_compute_metrics_none_found(self):
        """문단이 하나도 안 찾아진 경우 recall=0, mrr=0이어야 한다."""
        from eval.evaluate import compute_metrics

        result = {
            "expected_paragraphs": ["14", "15"],
            "found_paragraphs": [],
            "first_correct_rank": None,
            "expected_standard": "K-IFRS 1037",
            "primary_standard": "K-IFRS 1115",
        }
        metrics = compute_metrics(result)
        assert metrics["recall"] == 0.0
        assert metrics["mrr"] == 0.0
        assert metrics["std_accuracy"] == 0

    def test_run_single_evaluation(self):
        """단일 질문에 대해 run_evaluation이 동작해야 한다."""
        from eval.evaluate import load_golden, run_evaluation

        data = load_golden()
        result = run_evaluation(data[0])

        assert "found_paragraphs" in result
        assert "primary_standard" in result
        assert "first_correct_rank" in result
        assert isinstance(result["found_paragraphs"], list)
