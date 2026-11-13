from housing_netherlands.config import Settings
from housing_netherlands.workers.main import periodic_tasks


def test_sync_runs_on_its_interval_and_can_be_switched_off() -> None:
    tasks = periodic_tasks(Settings(sync_city="rotterdam", sync_every_min=15))
    assert set(tasks) == {"reconcile_jobs", "summarize_backlog", "sync_listings"}
    assert tasks["sync_listings"].every_min == 15

    assert "sync_listings" not in periodic_tasks(Settings(sync_city=""))


def test_summary_runs_get_time_for_their_last_llm_call() -> None:
    settings = Settings(summary_batch_s=240, llm_timeout_s=120)
    assert periodic_tasks(settings)["summarize_backlog"].timeout_s == 240 + 2 * 120 + 30
