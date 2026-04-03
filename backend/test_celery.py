import asyncio

from workers.queue import celery_app
from workers import tasks as worker_tasks


class _FakePool:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "OK"


def test_save_chat_message_runs_eager_without_broker(monkeypatch):
    fake_pool = _FakePool()
    previous_eager = celery_app.conf.task_always_eager
    previous_backend = celery_app.conf.result_backend
    previous_broker = celery_app.conf.broker_url

    async def _get_pool():
        return fake_pool

    def _run_async(coro):
        return asyncio.run(coro)

    monkeypatch.setattr(worker_tasks, "get_pool", _get_pool)
    monkeypatch.setattr(worker_tasks, "run_async", _run_async)
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "result_backend", "cache+memory://")
    monkeypatch.setattr(celery_app.conf, "broker_url", "memory://")

    try:
        result = worker_tasks.save_chat_message.apply(args=("session-1", "user", "hello", {"test": True}))
    finally:
        celery_app.conf.task_always_eager = previous_eager
        celery_app.conf.result_backend = previous_backend
        celery_app.conf.broker_url = previous_broker

    assert result.successful()
    assert len(fake_pool.calls) >= 2
    assert "INSERT INTO messages" in fake_pool.calls[0][0]
