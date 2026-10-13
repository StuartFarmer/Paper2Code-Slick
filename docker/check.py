"""Trusted container entry point; never import this module on the controller host."""

import importlib
import json
import os
import re
import sys
import traceback
from pathlib import Path, PurePosixPath


def main():
    spec = json.loads(sys.argv[1])
    kind, targets = spec["kind"], spec["targets"]
    if kind not in {"syntax", "imports", "pytest", "smoke"} or not targets:
        raise ValueError("Invalid registered check")
    for target in targets:
        path = target.split("::")[0]
        if kind == "imports":
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", target):
                raise ValueError("Invalid module")
        elif (
            PurePosixPath(path).is_absolute()
            or any(p.startswith(".") or not p for p in path.split("/"))
            or "\\" in path
            or not path.endswith(".py")
        ):
            raise ValueError("Invalid check path")
        if kind in {"pytest", "smoke"} and (
            not path.startswith("tests/acceptance/") or "::" not in target
        ):
            raise ValueError("Unregistered acceptance node")
    sys.path.insert(0, "/workspace")
    outcome = {
        "kind": kind,
        "targets": targets,
        "exit_code": 1,
        "collected": [],
        "passed": [],
        "failed": [],
        "skipped": [],
        "errors": [],
        "property_statistics": {},
    }
    try:
        if kind == "syntax":
            for target in targets:
                compile((Path("/workspace") / target).read_bytes(), target, "exec")
            outcome["exit_code"] = 0
        elif kind == "imports":
            for target in targets:
                importlib.import_module(target)
            outcome["exit_code"] = 0
        else:
            import pytest
            from _hypothesis_pytestplugin import STATS_KEY
            from hypothesis import Phase, settings

            profile = {
                "max_examples": 100,
                "derandomize": True,
                "database": None,
                "deadline": None,
                "print_blob": True,
                "suppress_health_check": [],
                "phases": [Phase.explicit, Phase.generate, Phase.shrink],
            }
            settings.register_profile("paper2code", **profile)
            settings.load_profile("paper2code")
            os.environ.pop("PYTEST_ADDOPTS", None)
            os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

            def node_id(item):
                return "tests/acceptance/" + item.split("tests/acceptance/", 1)[-1]

            class Results:
                def pytest_collection_finish(self, session):
                    outcome["collected"] = [node_id(item.nodeid) for item in session.items]
                    for item in session.items:
                        configured = getattr(
                            item.obj, "_hypothesis_internal_use_settings", settings.default
                        )
                        if any(
                            getattr(configured, key) != getattr(settings.default, key)
                            for key in profile
                        ):
                            raise pytest.UsageError(
                                "Acceptance tests cannot override the runner Hypothesis profile"
                            )

                def pytest_collectreport(self, report):
                    if report.failed:
                        outcome["errors"].append(str(report.longrepr))

                def pytest_runtest_logreport(self, report):
                    node = node_id(report.nodeid)
                    statistics = getattr(report, STATS_KEY, None)
                    if statistics:
                        outcome["property_statistics"][node] = {
                            "summary": statistics,
                            "valid_cases": None,
                            "invalid_cases": None,
                        }
                    if report.skipped:
                        outcome["skipped"].append(node)
                    elif report.failed:
                        outcome["failed" if report.when == "call" else "errors"].append(node)
                    elif report.when == "call":
                        outcome["passed"].append(node)

            plugin = Results()
            outcome["exit_code"] = int(
                pytest.main(
                    [
                        "-c",
                        "/runner/pytest.ini",
                        "--rootdir=/acceptance",
                        "--noconftest",
                        "-p",
                        "no:cacheprovider",
                        "-p",
                        "hypothesispytest",
                        "--hypothesis-show-statistics",
                        "-s",
                        "-q",
                        *["/acceptance/" + target for target in targets],
                    ],
                    plugins=[plugin],
                )
            )
            if not outcome["collected"] or outcome["skipped"] or outcome["errors"]:
                outcome["exit_code"] = outcome["exit_code"] or 1
            if outcome["exit_code"] in {2, 3, 4, 5}:
                outcome["errors"].append("Pytest setup/collection/usage failure")
    except Exception as error:  # noqa: BLE001 - serialize generated-code failures at the process boundary
        traceback.print_exc()
        outcome["errors"].append(f"{type(error).__name__}: {error}")
    print("\nP2C_RESULT=" + json.dumps(outcome), flush=True)
    return outcome["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
