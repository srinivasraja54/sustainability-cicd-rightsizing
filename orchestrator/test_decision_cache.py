"""Tests for the sizing-decision cache.

These run with no Azure account and no network: the blob container is
faked, so what's under test is the caching *contract* the README claims —
one LLM call per workflow change, and never a hard failure when the cache
is unavailable.
"""

from __future__ import annotations

import json

import decision_cache
import pytest
from azure.core.exceptions import AzureError, ResourceNotFoundError
from sizing_rules import SizingDecision

WORKFLOW = "steps:\n  - run: terraform apply -auto-approve\n"
LLM_DECISION = SizingDecision("medium", "aca-medium", "terraform apply", "llm")


class FakeBlob:
    def __init__(self, store: dict, name: str, error: Exception | None = None):
        self._store = store
        self._name = name
        self._error = error

    def download_blob(self):
        if self._error:
            raise self._error
        if self._name not in self._store:
            raise ResourceNotFoundError(f"no blob {self._name}")
        payload = self._store[self._name]

        class _Stream:
            def readall(self_inner):
                return payload

        return _Stream()

    def upload_blob(self, data, overwrite=False):
        if self._error:
            raise self._error
        self._store[self._name] = data


class FakeContainer:
    """Minimal stand-in for azure.storage.blob.ContainerClient."""

    def __init__(self, error: Exception | None = None):
        self.store: dict[str, str] = {}
        self.error = error

    def get_blob_client(self, name: str) -> FakeBlob:
        return FakeBlob(self.store, name, self.error)


def _key(workflow: str = WORKFLOW, deployment: str = "gpt-4o-mini", prompt: str = "P"):
    return decision_cache.key_for(workflow, deployment=deployment, prompt=prompt)


# --- key derivation ---


def test_key_is_stable_across_calls():
    assert _key() == _key()


def test_key_changes_when_workflow_changes():
    assert _key() != _key(workflow=WORKFLOW + "  - run: echo extra\n")


def test_key_changes_when_prompt_changes():
    assert _key() != _key(prompt="P2")


def test_key_changes_when_deployment_changes():
    assert _key() != _key(deployment="gpt-4o")


def test_key_separates_adjacent_fields():
    """Without a separator, ('ab','c') and ('a','bc') would collide."""
    a = decision_cache.key_for("c", deployment="ab", prompt="p")
    b = decision_cache.key_for("bc", deployment="a", prompt="p")
    assert a != b


# --- round trip ---


def test_put_then_get_returns_the_decision():
    container = FakeContainer()
    key = _key()

    assert decision_cache.put(key, LLM_DECISION, container=container) is True
    hit = decision_cache.get(key, container=container)

    assert hit is not None
    assert hit.size == "medium"
    assert hit.label == "aca-medium"
    assert hit.reason == "terraform apply"
    # Source flips so a run can be seen to have skipped the model.
    assert hit.source == decision_cache.CACHED_SOURCE


def test_get_is_a_miss_for_an_unknown_key():
    assert decision_cache.get(_key(), container=FakeContainer()) is None


def test_edited_workflow_misses_the_cache():
    container = FakeContainer()
    decision_cache.put(_key(), LLM_DECISION, container=container)

    edited = _key(workflow=WORKFLOW + "  - run: pytest\n")
    assert decision_cache.get(edited, container=container) is None


# --- degradation: never block CI ---


def test_unreachable_storage_is_a_miss_not_an_error():
    container = FakeContainer(error=AzureError("403 forbidden"))
    assert decision_cache.get(_key(), container=container) is None


def test_failed_write_is_reported_but_not_raised():
    container = FakeContainer(error=AzureError("network down"))
    assert decision_cache.put(_key(), LLM_DECISION, container=container) is False


def test_corrupt_entry_is_a_miss():
    container = FakeContainer()
    key = _key()
    container.store[f"{key}.json"] = "{not json"
    assert decision_cache.get(key, container=container) is None


def test_entry_with_unknown_size_is_a_miss():
    container = FakeContainer()
    key = _key()
    container.store[f"{key}.json"] = json.dumps({"size": "xl", "reason": "r"})
    assert decision_cache.get(key, container=container) is None


def test_enabled_follows_the_env_var(monkeypatch):
    monkeypatch.delenv(decision_cache.ACCOUNT_URL_ENV, raising=False)
    assert decision_cache.enabled() is False

    monkeypatch.setenv(
        decision_cache.ACCOUNT_URL_ENV, "https://x.blob.core.windows.net"
    )
    assert decision_cache.enabled() is True


def test_missing_env_var_is_a_miss_not_a_crash(monkeypatch):
    """get() with no container and no env var must not raise KeyError."""
    monkeypatch.delenv(decision_cache.ACCOUNT_URL_ENV, raising=False)
    assert decision_cache.get(_key()) is None


@pytest.mark.parametrize("size", ["small", "medium", "large"])
def test_round_trip_preserves_every_tier(size):
    container = FakeContainer()
    key = _key(workflow=f"steps: {size}")
    decision_cache.put(
        key, SizingDecision(size, f"aca-{size}", "why", "llm"), container=container
    )
    hit = decision_cache.get(key, container=container)
    assert hit is not None and hit.size == size and hit.label == f"aca-{size}"
