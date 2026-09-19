"""Small local SQLite run store with no network dependency."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .run_types import SessionResult


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_runs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS assessment_runs_created_at
                ON assessment_runs(created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessment_run_artifacts (
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    artifact BLOB NOT NULL,
                    PRIMARY KEY (run_id, kind)
                )
                """
            )
            legacy_tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "voice_runs" in legacy_tables:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO assessment_runs(
                        run_id, mode, verdict, result_json, created_at
                    )
                    SELECT run_id, mode, verdict, result_json, created_at
                    FROM voice_runs
                    """
                )
                connection.execute("DROP TABLE voice_runs")
            if "voice_run_artifacts" in legacy_tables:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO assessment_run_artifacts(
                        run_id, kind, media_type, artifact
                    )
                    SELECT run_id, kind, media_type, artifact
                    FROM voice_run_artifacts
                    """
                )
                connection.execute("DROP TABLE voice_run_artifacts")

    def save(self, result: SessionResult) -> Dict[str, Any]:
        result_dict = result.to_dict()
        exchange = result_dict.get("metadata", {}).get("exchange", {})
        response_metadata = exchange.get("response_metadata", {})
        artifacts: list[tuple[str, str, bytes]] = []
        audio_url = response_metadata.pop("response_audio_data_url", None)
        if isinstance(audio_url, str) and audio_url.startswith("data:audio/"):
            header, encoded = audio_url.split(",", 1)
            media_type = header[5:].split(";", 1)[0]
            artifacts.append(
                (
                    "response_audio",
                    media_type,
                    base64.b64decode(encoded, validate=True),
                )
            )
            response_metadata["response_audio_url"] = (
                f"/api/runs/{result.run_id}/audio"
            )
        observation = response_metadata.get("observation")
        if isinstance(observation, dict):
            for phase in ("before", "after"):
                captured = observation.get(phase)
                if not isinstance(captured, dict):
                    continue
                screenshot_url = captured.pop("screenshot_data_url", None)
                if not isinstance(screenshot_url, str) or not screenshot_url.startswith(
                    "data:image/png;base64,"
                ):
                    continue
                kind = f"observation_{phase}"
                encoded = screenshot_url.split(",", 1)[1]
                artifacts.append(
                    (kind, "image/png", base64.b64decode(encoded, validate=True))
                )
                captured["screenshot_url"] = (
                    f"/api/runs/{result.run_id}/artifacts/{kind}"
                )
        payload = json.dumps(result_dict, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assessment_runs(run_id, mode, verdict, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (result.run_id, result.mode, result.analysis.verdict.value, payload),
            )
            for kind, media_type, artifact in artifacts:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO assessment_run_artifacts(
                        run_id, kind, media_type, artifact
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (result.run_id, kind, media_type, artifact),
                )
        return result_dict

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM assessment_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result_json FROM assessment_runs
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row["result_json"]) for row in rows]

    def get_audio(self, run_id: str) -> Optional[tuple[str, bytes]]:
        return self.get_artifact(run_id, "response_audio")

    def get_artifact(self, run_id: str, kind: str) -> Optional[tuple[str, bytes]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT media_type, artifact FROM assessment_run_artifacts
                WHERE run_id = ? AND kind = ?
                """,
                (run_id, kind),
            ).fetchone()
        if row is None:
            return None
        return str(row["media_type"]), bytes(row["artifact"])
