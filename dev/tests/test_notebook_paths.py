"""TDD RED — agent_evaluation.ipynb 경로 문제 검증 테스트.

노트북이 어떤 cwd에서든 올바르게 파일을 참조할 수 있는지 확인.
핵심: evaluate_agent.GOLDEN_PATH를 import해서 모든 경로를 파생해야 한다.
"""

from pathlib import Path


def test_golden_path_importable():
    """GOLDEN_PATH가 eval.evaluate_agent에서 import 가능해야 한다."""
    from eval.evaluate_agent import GOLDEN_PATH

    assert isinstance(GOLDEN_PATH, Path)


def test_golden_path_points_to_existing_file():
    """GOLDEN_PATH가 실제 존재하는 golden_dataset.json을 가리켜야 한다."""
    from eval.evaluate_agent import GOLDEN_PATH

    assert GOLDEN_PATH.exists(), f"GOLDEN_PATH가 존재하지 않음: {GOLDEN_PATH}"
    assert GOLDEN_PATH.name == "golden_dataset.json"


def test_results_dir_derivable_from_golden_path():
    """GOLDEN_PATH.parent / 'results'로 결과 디렉토리를 파생할 수 있어야 한다."""
    from eval.evaluate_agent import GOLDEN_PATH

    results_dir = GOLDEN_PATH.parent / "results"
    assert results_dir.exists(), f"results 디렉토리가 존재하지 않음: {results_dir}"
    assert results_dir.is_dir()


def test_golden_path_works_regardless_of_cwd(tmp_path, monkeypatch):
    """cwd가 프로젝트 루트가 아니어도 GOLDEN_PATH는 절대경로로 동작해야 한다."""
    # cwd를 임시 디렉토리로 변경
    monkeypatch.chdir(tmp_path)

    from eval.evaluate_agent import GOLDEN_PATH

    assert GOLDEN_PATH.is_absolute(), f"GOLDEN_PATH가 절대경로가 아님: {GOLDEN_PATH}"
    assert GOLDEN_PATH.exists(), f"cwd 변경 후 GOLDEN_PATH를 찾을 수 없음: {GOLDEN_PATH}"


def test_relative_path_fails_from_notebook_dir():
    """상대경로 'dev/eval/golden_dataset.json'은 notebooks/ cwd에서 실패해야 한다.

    이 테스트는 문제의 root cause를 증명한다:
    노트북 디렉토리에서 상대경로로 접근하면 파일을 찾을 수 없다.
    """
    notebook_dir = Path(__file__).resolve().parent.parent / "notebooks"
    relative_path = notebook_dir / "dev" / "eval" / "golden_dataset.json"

    # notebooks/dev/eval/golden_dataset.json 은 존재하지 않아야 함
    assert not relative_path.exists(), (
        "상대경로가 우연히 동작하면 안 됨 — 이 테스트는 문제를 증명하기 위한 것"
    )
