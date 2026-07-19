"""Apify retry-policy tests — no network, no credit spend, no LLM.

Every case stubs the single-attempt layer (or requests.post) and asserts how many
attempts the policy in _run_actor() actually makes. The point is that retries stay
narrow: Apify bills by compute unit, so retrying a run that already completed costs
real money.
"""
import apify_scraper as aps
import pytest


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep backoff from actually sleeping during tests."""
    monkeypatch.setattr(aps.time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(aps, "_apify_blocked", False)
    monkeypatch.setattr(aps, "_retry_empty_runs", False)


def _stub_once(monkeypatch, responses):
    """Stub _run_actor_once with a scripted list of (items, err, retryable)."""
    calls = []

    def fake(actor_id, run_input, token, timeout):
        calls.append(actor_id)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(aps, "_run_actor_once", fake)
    return calls


# ── retryable transport failures ──────────────────────────────────────────────

def test_transient_then_success_retries(monkeypatch):
    calls = _stub_once(monkeypatch, [([], None, True), ([{"a": 1}], None, False)])
    items, err = aps._run_actor("act", {}, "tok", 10)
    assert len(calls) == 2
    assert items == [{"a": 1}]
    assert err is None


def test_persistent_transient_stops_at_max_retries(monkeypatch):
    calls = _stub_once(monkeypatch, [([], None, True)])
    items, err = aps._run_actor("act", {}, "tok", 10)
    assert len(calls) == aps.MAX_RETRIES
    assert items == [] and err is None


# ── non-retryable failures ────────────────────────────────────────────────────

def test_auth_error_does_not_retry(monkeypatch):
    calls = _stub_once(monkeypatch, [([], "auth", False)])
    items, err = aps._run_actor("act", {}, "tok", 10)
    assert len(calls) == 1
    assert err == "auth"


def test_credit_error_does_not_retry(monkeypatch):
    calls = _stub_once(monkeypatch, [([], "credit", False)])
    items, err = aps._run_actor("act", {}, "tok", 10)
    assert len(calls) == 1
    assert err == "credit"


def test_schema_error_does_not_retry(monkeypatch):
    """HTTP 400 is deterministic — retrying only burns wall-clock."""
    calls = _stub_once(monkeypatch, [([], None, False)])
    items, err = aps._run_actor("act", {}, "tok", 10)
    assert len(calls) == 1
    assert items == [] and err is None


# ── empty-result policy (the credit-sensitive one) ────────────────────────────

def test_empty_result_accepted_by_default(monkeypatch):
    calls = _stub_once(monkeypatch, [([], None, False)])
    aps._run_actor("act", {}, "tok", 10, retry_empty=False)
    assert len(calls) == 1


def test_empty_result_retried_once_when_enabled(monkeypatch):
    calls = _stub_once(monkeypatch, [([], None, False)])
    aps._run_actor("act", {}, "tok", 10, retry_empty=True)
    assert len(calls) == 2, "empty retry must be capped at one extra attempt"


def test_retry_empty_defaults_to_module_flag(monkeypatch):
    """run_actor_safe() with retry_empty=None honours actors.json config."""
    monkeypatch.setattr(aps, "_retry_empty_runs", True)
    calls = _stub_once(monkeypatch, [([], None, False)])
    aps.run_actor_safe("act", {}, {"token": "t"}, "linkedin")
    assert len(calls) == 2


# ── raw-path classification (retryable flag derived from status) ──────────────

class _Resp:
    def __init__(self, status, body="", payload=None):
        self.status_code = status
        self.text = body
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


@pytest.mark.parametrize("status,exp_err,exp_retryable", [
    (500, None, True),
    (503, None, True),
    (408, None, True),
    (400, None, False),
    (401, "auth", False),
    (403, "auth", False),
    (402, "credit", False),
    (429, "credit", False),
])
def test_raw_path_classification(monkeypatch, status, exp_err, exp_retryable):
    monkeypatch.setattr(aps.requests, "post", lambda *a, **k: _Resp(status, "boom"))
    items, err, retryable = aps._run_actor_raw("act", {}, "tok", 10)
    assert items == []
    assert err == exp_err
    assert retryable is exp_retryable


def test_raw_path_transport_exception_is_retryable(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("reset")
    monkeypatch.setattr(aps.requests, "post", boom)
    _, err, retryable = aps._run_actor_raw("act", {}, "tok", 10)
    assert err is None and retryable is True


def test_raw_path_success_returns_items(monkeypatch):
    monkeypatch.setattr(aps.requests, "post",
                        lambda *a, **k: _Resp(200, payload=[{"title": "SWE"}]))
    items, err, retryable = aps._run_actor_raw("act", {}, "tok", 10)
    assert items == [{"title": "SWE"}] and err is None and retryable is False


# ── token re-prompt still intact (what the SDK error adapter protects) ────────

def test_credit_failure_triggers_single_token_reprompt(monkeypatch):
    calls = _stub_once(monkeypatch, [([], "credit", False)])
    prompts = []

    def fake_prompt(reason):
        prompts.append(reason)
        return "new-token"

    monkeypatch.setattr(aps, "prompt_for_new_token", fake_prompt)
    monkeypatch.setattr(aps, "normalize", lambda it, board, url_field="": it)

    out = aps.run_actor_safe("act", {}, {"token": "old"}, "linkedin")
    assert len(prompts) == 1, "must prompt exactly once"
    assert out == []
    assert aps._apify_blocked is True, "second failure must block Apify for the run"


def test_token_reprompt_propagates_new_token(monkeypatch):
    seen_tokens = []

    def fake(actor_id, run_input, token, timeout):
        seen_tokens.append(token)
        if token == "old":
            return [], "credit", False
        return [{"ok": 1}], None, False

    monkeypatch.setattr(aps, "_run_actor_once", fake)
    monkeypatch.setattr(aps, "prompt_for_new_token", lambda r: "fresh")
    monkeypatch.setattr(aps, "normalize", lambda it, board, url_field="": it)

    holder = {"token": "old"}
    out = aps.run_actor_safe("act", {}, holder, "linkedin")
    assert out == [{"ok": 1}]
    assert holder["token"] == "fresh", "refreshed token must persist for later actors"
    assert seen_tokens == ["old", "fresh"]


# ── SDK error adapter parity ──────────────────────────────────────────────────

class _ApiErr(Exception):
    def __init__(self, status, msg=""):
        super().__init__(msg or f"status {status}")
        self.status_code = status


@pytest.mark.parametrize("status,exp_err,exp_retryable", [
    (401, "auth", False),
    (402, "credit", False),
    (400, None, False),
    (500, None, True),
    (0, None, True),
])
def test_sdk_errors_classify_like_raw(monkeypatch, status, exp_err, exp_retryable):
    """The SDK raises instead of returning a status; both paths must agree,
    otherwise the credit/auth token re-prompt silently breaks under the SDK."""
    sdk = pytest.importorskip("apify_client")

    class _Client:
        def __init__(self, token):
            pass

        def actor(self, actor_id):
            raise _ApiErr(status)

    monkeypatch.setattr(sdk, "ApifyClient", _Client)
    items, err, retryable = aps._run_actor_sdk("act", {}, "tok", 10)
    assert items == []
    assert err == exp_err
    assert retryable is exp_retryable


# ── SDK major-version compat ──────────────────────────────────────────────────
# These run against the REAL installed client signature. A stubbed client would
# happily accept wait_secs= on 3.x and hide a TypeError that only shows up live.

def test_wait_kwargs_match_installed_sdk_signature():
    import inspect
    sdk = pytest.importorskip("apify_client")
    client = sdk.ApifyClient("token")
    kwargs = aps._sdk_wait_kwargs(client, 300)
    params = inspect.signature(client.actor("u/a").call).parameters
    assert kwargs, "must pass some wait argument"
    for k in kwargs:
        assert k in params, f"{k}= is not accepted by the installed apify-client"


def test_wait_kwargs_prefers_timedelta_on_3x():
    from datetime import timedelta
    sdk = pytest.importorskip("apify_client")
    client = sdk.ApifyClient("token")
    import inspect
    params = inspect.signature(client.actor("u/a").call).parameters
    kwargs = aps._sdk_wait_kwargs(client, 300)
    if "wait_duration" in params:
        assert kwargs["wait_duration"] == timedelta(seconds=300)
        assert kwargs.get("logger") is None, "actor log streaming must be silenced"
    else:
        assert kwargs["wait_secs"] == 300


def test_dataset_id_reads_both_run_shapes():
    """1.x hands back a dict; 3.x a pydantic model with no .get()."""
    assert aps._sdk_dataset_id({"defaultDatasetId": "ds1"}) == "ds1"

    class _Run3x:  # no .get(), snake_case attr — the 3.x shape
        default_dataset_id = "ds2"

    assert aps._sdk_dataset_id(_Run3x()) == "ds2"
    assert aps._sdk_dataset_id(object()) is None
