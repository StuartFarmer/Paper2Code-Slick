import asyncio

from providers import ScriptedProvider
from test_contracts import spec_plan, suite_for
from test_store import manifest

from codes.agent import PaperCoder
from codes.paper import index_paper
from codes.store import RunStore


def test_diamond_runs_siblings_together_and_blocks_descendants(tmp_path):
    source = tmp_path / "paper.md"
    source.write_text("Method")
    spec, plan = spec_plan()
    with RunStore.create(tmp_path / "run", manifest()) as store:
        coder = PaperCoder(store, ScriptedProvider([]))
        coder.configure_run(index_paper(source), spec, plan, suite_for(plan))
        entered = []

        async def exercise():
            sibling_barrier = asyncio.Event()

            async def task(task_spec):
                entered.append(task_spec.id)
                if task_spec.id in {"b", "c"}:
                    if "b" in entered and "c" in entered:
                        sibling_barrier.set()
                    await asyncio.wait_for(sibling_barrier.wait(), 1)
                record = coder.records[task_spec.id]
                record.state = "blocked" if task_spec.id == "c" else "accepted"
                return record

            coder.execute_task = task
            await coder.execute_plan()

        asyncio.run(exercise())
        assert entered[0] == "a" and set(entered[1:]) == {"b", "c"}
        assert coder.records["b"].state == "accepted"
        assert coder.records["d"].state == "blocked"


def test_model_semaphore_and_cancellation_preserve_reserved_budget(tmp_path, monkeypatch):
    from pathlib import Path

    from slick import prompts

    monkeypatch.setattr(
        prompts, "TEMPLATE_ROOT", Path(__file__).resolve().parents[1] / "codes/prompts"
    )
    settings = manifest()
    settings.limits.concurrency = 2
    settings.limits.max_calls = 10
    with RunStore.create(tmp_path / "run", settings) as store:

        async def exercise():
            entered = asyncio.Event()
            active = 0
            maximum = 0

            class WaitingProvider:
                async def acall(self, context, **kwargs):
                    nonlocal active, maximum
                    active += 1
                    maximum = max(maximum, active)
                    if active == 2:
                        entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        active -= 1

            coder = PaperCoder(store, WaitingProvider())
            pending = [
                asyncio.create_task(coder.invoke("extract_requirements", {}, task_id=str(n)))
                for n in range(5)
            ]
            await asyncio.wait_for(entered.wait(), 2)
            assert store.manifest.calls_reserved == maximum == 2
            for task in pending:
                task.cancel()
            results = await asyncio.gather(*pending, return_exceptions=True)
            assert all(isinstance(r, asyncio.CancelledError) for r in results)
            assert active == 0 and store.manifest.calls_reserved == 2

        asyncio.run(exercise())
        assert "cancelled" in store.read_artifact("calls/call-00001/outcome.json")
