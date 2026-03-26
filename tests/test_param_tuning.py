"""RRF 파라미터 튜닝 테스트.

evaluate 모듈이 다양한 검색 설정(rrf_k, pool_size, dense-only, bm25-only)으로
평가를 실행하고 결과를 비교할 수 있는지 검증.
"""

import pytest
from dotenv import load_dotenv

load_dotenv()

from eval.evaluate import run_evaluation, load_golden, SEARCH_CONFIGS


class TestSearchConfigs:
    """검색 설정 구조 검증."""

    def test_configs_dict_exists(self):
        """SEARCH_CONFIGS 딕셔너리가 존재해야 한다."""
        assert isinstance(SEARCH_CONFIGS, dict)

    def test_baseline_config_exists(self):
        """baseline 설정이 존재해야 한다."""
        assert "baseline" in SEARCH_CONFIGS

    def test_configs_have_required_keys(self):
        """각 설정에 필수 키(rrf_k, pool_size, mode)가 있어야 한다."""
        required = {"rrf_k", "pool_size", "mode"}
        for name, cfg in SEARCH_CONFIGS.items():
            missing = required - set(cfg.keys())
            assert not missing, f"{name}: 누락 키 {missing}"

    def test_dense_only_config_exists(self):
        """dense-only 설정이 존재해야 한다."""
        assert "dense_only" in SEARCH_CONFIGS
        assert SEARCH_CONFIGS["dense_only"]["mode"] == "dense_only"

    def test_bm25_only_config_exists(self):
        """bm25-only 설정이 존재해야 한다."""
        assert "bm25_only" in SEARCH_CONFIGS
        assert SEARCH_CONFIGS["bm25_only"]["mode"] == "bm25_only"


class TestConfiguredEvaluation:
    """설정별 평가 실행 검증."""

    def test_run_evaluation_accepts_config(self):
        """run_evaluation이 config 파라미터를 받을 수 있어야 한다."""
        golden = load_golden()
        config = SEARCH_CONFIGS["baseline"]
        result = run_evaluation(golden[0], config=config)

        assert "found_paragraphs" in result
        assert "primary_standard" in result

    def test_different_configs_produce_results(self):
        """서로 다른 설정으로 평가 시 모두 결과를 반환해야 한다."""
        golden = load_golden()
        item = golden[0]  # q001: 충당부채 인식

        for name in ["baseline", "dense_only"]:
            config = SEARCH_CONFIGS[name]
            result = run_evaluation(item, config=config)
            assert isinstance(result["found_paragraphs"], list), (
                f"{name} 설정에서 결과 없음"
            )
