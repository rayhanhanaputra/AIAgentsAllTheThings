import base64
import json
import sqlite3
from dataclasses import replace

from harness.api.run_store import RunStore
from harness.api.run_types import (
    AnalysisResult,
    RunState,
    SessionResult,
    Verdict,
)


def test_legacy_voice_tables_are_migrated_without_losing_runs(tmp_path):
    database = tmp_path / "runs.db"
    result = {"run_id": "legacy-run", "mode": "workbench"}
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE voice_runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                verdict TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO voice_runs VALUES (?, ?, ?, ?, ?)",
            (
                "legacy-run",
                "workbench",
                "inconclusive",
                json.dumps(result),
                "2026-01-01T00:00:00+00:00",
            ),
        )

    store = RunStore(database)

    assert store.get("legacy-run") == result
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "assessment_runs" in tables
    assert "voice_runs" not in tables


def test_observation_screenshots_are_stored_as_separate_artifacts(tmp_path):
    result = SessionResult(
        run_id="run-observation",
        mode="workbench",
        state=RunState.COMPLETED,
        provider="device-bridge",
        script="safe observation",
        response_text="idle",
        canary="",
        duration_ms=10,
        events=[],
        analysis=AnalysisResult(
            verdict=Verdict.INCONCLUSIVE,
            canary_matches=0,
            evidence=["Fixture result."],
        ),
    )
    png = b"\x89PNG\r\n\x1a\nfixture"
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    result = replace(
        result,
        metadata={
            "exchange": {
                "response_metadata": {
                    "observation": {
                        "before": {"text": "idle", "screenshot_data_url": data_url},
                        "after": {"text": "changed", "screenshot_data_url": data_url},
                    }
                }
            }
        },
    )
    store = RunStore(tmp_path / "runs.db")

    saved = store.save(result)

    observation = saved["metadata"]["exchange"]["response_metadata"]["observation"]
    assert observation["before"]["screenshot_url"].endswith(
        "/artifacts/observation_before"
    )
    assert observation["after"]["screenshot_url"].endswith(
        "/artifacts/observation_after"
    )
    assert store.get_artifact(result.run_id, "observation_before") == (
        "image/png",
        png,
    )
