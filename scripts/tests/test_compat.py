import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compat


@pytest.mark.parametrize(
    ("bundle_exists", "source_drift", "host_hash", "deployed_hash", "failure_count"),
    [
        (True, [], "same", "same", 0),
        (True, ["changed module.py"], "same", "same", 1),
        (True, [], "host", "deployed", 1),
        (False, [], None, None, 1),
    ],
)
def test_bundle_state_failures(
    bundle_exists: bool,
    source_drift: list[str],
    host_hash: str | None,
    deployed_hash: str | None,
    failure_count: int,
) -> None:
    failures = compat._bundle_state_failures(bundle_exists, source_drift, host_hash, deployed_hash)

    assert len(failures) == failure_count
