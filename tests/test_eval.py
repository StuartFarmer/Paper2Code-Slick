import json
from pathlib import Path

import pytest
from providers import ScriptedExecutor

from eval.run import calibrate, evaluate


def test_evaluation_freezes_external_checks_and_counts_failed_run(tmp_path):
    seen = []

    def failed_run(argv):
        seen.extend(argv)
        root = Path(argv[argv.index("--output-dir") + 1])
        root.mkdir()
        (root / "report.json").write_text(
            json.dumps({"outcome": "incomplete", "calls_reserved": 30, "measured_cost": None})
        )
        return 1

    result = evaluate(
        "micro", tmp_path / "eval", image=("sha256:test", "linux/arm64"), workflow=failed_run
    )
    assert result["outcome"] == "incomplete" and result["calls_reserved"] == 30
    assert result["measured_cost"] is None
    assert result["external_check"] is None
    assert "--max-calls" in seen and seen[seen.index("--max-calls") + 1] == "30"
    assert result["acceptance_hash"] and result["paper_hash"]
    assert "acceptance" not in " ".join(seen)


def test_stage_promotion_requires_passing_previous_stage(tmp_path):
    with pytest.raises(ValueError, match="previous"):
        evaluate("component", tmp_path / "eval", image=("sha256:test", "linux/arm64"))
    assert not (tmp_path / "eval").exists()


def test_calibration_does_not_count_setup_errors_as_rejected_faults(tmp_path):
    import asyncio

    executor = ScriptedExecutor(
        ["passed", "infrastructure_error", "passed", "failed", "passed", "failed"]
    )
    result = asyncio.run(calibrate(tmp_path / "calibration", "sha256:test", executor=executor))
    assert result["reference_passed"] == 3
    assert result["faults_rejected"] == 2
    assert result["inconclusive"] == 1
    assert result["pairs"] == 3
