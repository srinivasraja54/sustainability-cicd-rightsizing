"""End-to-end tests for the rules → cache → LLM decision path.

The point of these is the claim in the README: *the LLM is called once per
workflow change, not once per run*. That is a statement about call counts,
so these tests count calls. The Azure OpenAI call and the blob container
are both faked — no network, no credentials.
"""

from __future__ import annotations

import azure_openai_client
import decision_cache
import pytest
from analyze_pipeline import analyze
from sizing_rules import SizingDecision
from test_decision_cache import FakeContainer

AMBIGUOUS = "steps:\n  - run: terraform -chdir=infra/tf apply -auto-approve\n"
OBVIOUS = "steps:\n  - run: pytest --cov\n"


@pytest.fixture
def workflow(tmp_path):
    def _write(text: str, name: str = "wf.yml"):
        path = tmp_path / name
        path.write_text(text)
        return path

    return _write


@pytest.fixture
def llm_calls(monkeypatch):
    """Replace the Azure OpenAI call with a counter."""
    calls = []

    def fake_decide(workflow_yaml, cfg):
        calls.append(workflow_yaml)
        return SizingDecision("large", "aca-large", "terraform apply is heavy", "llm")

    monkeypatch.setattr(azure_openai_client, "decide_with_llm", fake_decide)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    return calls


@pytest.fixture
def cache(monkeypatch):
    """Point decision_cache at an in-memory container."""
    container = FakeContainer()
    monkeypatch.setenv(
        decision_cache.ACCOUNT_URL_ENV, "https://fake.blob.core.windows.net"
    )
    monkeypatch.setattr(decision_cache, "DefaultAzureCredential", lambda *a, **k: None)
    monkeypatch.setattr(decision_cache, "ContainerClient", lambda **kwargs: container)
    return container


def test_rules_path_never_calls_the_llm(workflow, llm_calls, cache):
    result = analyze(workflow(OBVIOUS))
    assert result["source"] == "rules"
    assert result["size"] == "medium"
    assert llm_calls == []


def test_ambiguous_workflow_calls_the_llm_once_then_caches(workflow, llm_calls, cache):
    path = workflow(AMBIGUOUS)

    first = analyze(path)
    assert first["source"] == "llm"
    assert first["size"] == "large"
    assert len(llm_calls) == 1

    # Ten more dispatches of the same unchanged workflow.
    for _ in range(10):
        again = analyze(path)
        assert again["source"] == decision_cache.CACHED_SOURCE
        assert again["size"] == "large"
        assert again["reason"] == "terraform apply is heavy"

    assert len(llm_calls) == 1, "cache did not prevent repeat LLM calls"


def test_editing_the_workflow_triggers_exactly_one_new_call(workflow, llm_calls, cache):
    path = workflow(AMBIGUOUS)
    analyze(path)
    assert len(llm_calls) == 1

    path.write_text(AMBIGUOUS + "  - run: terraform output -json\n")
    analyze(path)
    assert len(llm_calls) == 2, "edited workflow should re-decide"

    analyze(path)
    assert len(llm_calls) == 2, "edited workflow should then be cached too"


def test_changing_the_deployment_invalidates_the_entry(
    workflow, llm_calls, cache, monkeypatch
):
    path = workflow(AMBIGUOUS)
    analyze(path)
    assert len(llm_calls) == 1

    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    analyze(path)
    assert len(llm_calls) == 2, "a model swap must not reuse the old decision"


def test_no_cache_flag_forces_a_fresh_call(workflow, llm_calls, cache):
    path = workflow(AMBIGUOUS)
    analyze(path)
    analyze(path, use_cache=False)
    analyze(path, use_cache=False)
    assert len(llm_calls) == 3


def test_unconfigured_cache_still_produces_a_decision(workflow, llm_calls, monkeypatch):
    monkeypatch.delenv(decision_cache.ACCOUNT_URL_ENV, raising=False)
    result = analyze(workflow(AMBIGUOUS))
    assert result["source"] == "llm"
    assert len(llm_calls) == 1


def test_broken_cache_falls_through_to_the_llm(workflow, llm_calls, monkeypatch):
    """A storage outage must degrade to cost, not to a failed pipeline."""
    from azure.core.exceptions import AzureError

    monkeypatch.setenv(
        decision_cache.ACCOUNT_URL_ENV, "https://fake.blob.core.windows.net"
    )
    monkeypatch.setattr(decision_cache, "DefaultAzureCredential", lambda *a, **k: None)
    monkeypatch.setattr(
        decision_cache,
        "ContainerClient",
        lambda **kwargs: FakeContainer(error=AzureError("storage unreachable")),
    )

    result = analyze(workflow(AMBIGUOUS))
    assert result["source"] == "llm"
    assert result["size"] == "large"
    assert len(llm_calls) == 1


def test_no_llm_flag_is_unaffected_by_the_cache(workflow, llm_calls, cache):
    result = analyze(workflow(AMBIGUOUS), allow_llm=False)
    assert result["source"] == "default"
    assert result["size"] == "medium"
    assert llm_calls == []


def test_failed_llm_call_falls_back_to_medium_and_is_not_cached(
    workflow, cache, monkeypatch
):
    """An LLM outage must degrade to a default size, not to a failed pipeline."""
    calls = []

    def failing_decide(workflow_yaml, cfg):
        calls.append(workflow_yaml)
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(azure_openai_client, "decide_with_llm", failing_decide)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

    path = workflow(AMBIGUOUS)
    result = analyze(path)
    assert result["source"] == "default"
    assert result["size"] == "medium"
    assert "LLM call failed" in result["reason"]

    analyze(path)
    assert len(calls) == 2, "a fallback must not be cached; retry the LLM next run"


def test_unconfigured_llm_falls_back_to_medium(workflow, cache, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    result = analyze(workflow(AMBIGUOUS))
    assert result["source"] == "default"
    assert result["size"] == "medium"
