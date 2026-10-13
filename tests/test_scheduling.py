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
