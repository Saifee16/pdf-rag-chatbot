from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluation import run_ocr_benchmark


def test_ocr_benchmark_reports_safe_fixture_metrics(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "ocr-report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ocr_benchmark", "--output", str(output)],
    )

    run_ocr_benchmark.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["engine"] == "deterministic_fixture_adapter"
    assert report["query_count"] == 6
    assert report["retrieval_recall_at_3"] == 1.0
    assert report["citation_page_accuracy"] == 1.0
    assert report["cases"][-1]["error_code"] == "OCR_TOO_MANY_PAGES"


def test_ocr_benchmark_real_engine_path_can_be_run_with_local_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "real-ocr-report.json"

    def fake_ocr(**_kwargs):
        return run_ocr_benchmark.FixtureOCR(
            {
                1: "Scanned retention policy: retain customer records for ninety days.",
                2: "Scanned escalation policy: manager approval is required.",
            }
        )

    monkeypatch.setattr(run_ocr_benchmark, "OCRService", fake_ocr)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_ocr_benchmark", "--real-ocr", "--output", str(output)],
    )

    run_ocr_benchmark.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["engine"] == "tesseract"
    assert report["query_count"] == 6
