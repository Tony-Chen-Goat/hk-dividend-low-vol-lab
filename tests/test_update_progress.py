from datetime import datetime, timezone

from app.update_progress import format_duration, update_progress_metrics


def test_running_progress_calculates_percentage_and_eta():
    state = {
        "status": "running",
        "started_at": "2026-09-04T10:00:00+08:00",
        "updated_at": "2026-09-04T10:04:00+08:00",
        "requested_count": 100,
        "completed_count": 25,
        "current_symbol": "0700.HK",
    }

    metrics = update_progress_metrics(
        state,
        now=datetime(2026, 9, 4, 2, 5, tzinfo=timezone.utc),
    )

    assert metrics["percent"] == 25.0
    assert metrics["remaining"] == 75
    assert metrics["elapsed_seconds"] == 300.0
    assert metrics["eta_seconds"] == 900.0
    assert metrics["seconds_since_update"] == 60.0


def test_progress_values_are_clamped_and_duration_is_readable():
    metrics = update_progress_metrics({
        "status": "completed",
        "requested_count": 10,
        "completed_count": 12,
        "elapsed_seconds": 3661,
    })

    assert metrics["completed"] == 10
    assert metrics["percent"] == 100.0
    assert metrics["eta_seconds"] == 0.0
    assert format_duration(metrics["elapsed_seconds"]) == "1小时1分钟"
    assert format_duration(None) == "估算中"
