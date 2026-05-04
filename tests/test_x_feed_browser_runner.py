import json

import pytest


def test_extract_response_region_trims_prompt_and_thought_block():
    from tradingagents.dealflow.sources.x_feed_browser_runner import extract_response_region

    prompt = 'Return JSON only: {"schema":"example"}'
    main_text = (
        'Share\n\n'
        + prompt
        + '\n\nThought for 7s\n\n{"trending":[{"ticker":"NVDA"}]}\n\nExplore related ideas'
    )

    extracted = extract_response_region(main_text, prompt)

    assert extracted.startswith('{"trending":[{"ticker":"NVDA"}]}')
    assert prompt not in extracted


def test_prompts_match_when_only_blank_lines_differ():
    from tradingagents.dealflow.sources.x_feed_browser_runner import prompts_match_for_submission

    expected = "line one\n- bullet a\n- bullet b\nline two"
    actual = "line one\n\n- bullet a\n\n- bullet b\nline two"

    assert prompts_match_for_submission(expected, actual) is True


def test_extract_last_response_index_returns_highest_response_li():
    from tradingagents.dealflow.sources.x_feed_browser_runner import extract_last_response_index

    state = """
viewport: 1710x870
[7]<div contenteditable=true />
*[1507]<li level=1 />
\t*[1506]<div />
\t\t*[1503]<div />
\t\t\t{\"ok\":true}
*[1602]<li level=1 />
\t*[1601]<div />
\t\t*[1599]<div />
\t\t\t{\"ok\":false}
"""

    assert extract_last_response_index(state) == 1602


def test_run_browser_passes_iterates_requested_range_and_ingests_each_pass():
    from tradingagents.dealflow.sources.x_feed_browser_runner import run_browser_passes

    prompts = [
        (1, "Pass 1", "prompt-1"),
        (2, "Pass 2", "prompt-2"),
        (3, "Pass 3", "prompt-3"),
        (4, "Pass 4", "prompt-4"),
    ]

    class FakeSession:
        def __init__(self):
            self.open_calls = 0
            self.ensure_calls = 0
            self.submitted_prompts = []
            self.responses = {
                "prompt-2": json.dumps({"trending": [{"ticker": "MSFT"}]}),
                "prompt-3": json.dumps({"trending": [{"ticker": "NVDA"}]}),
            }

        def open_fresh_chat(self):
            self.open_calls += 1

        def wait_until_chat_ready(self, timeout_seconds: int = 30, poll_interval_seconds: float = 1.0) -> str:
            return "[7]<div contenteditable=true />\n[736]<button id=model-select-trigger aria-label=Model select />"

        def ensure_expert(self):
            self.ensure_calls += 1

        def submit_prompt(self, prompt: str):
            self.submitted_prompts.append(prompt)

        def wait_for_response_text(self, timeout_seconds: int = 300) -> str:
            return self.responses[self.submitted_prompts[-1]]

    session = FakeSession()
    ingest_calls = []

    def _ingest(as_of_date: str, raw_text: str, pass_num: int, dry_run: bool = False):
        ingest_calls.append((as_of_date, pass_num, raw_text, dry_run))
        return {"pass_num": pass_num, "tickers_parsed": 1, "tickers_merged": len(ingest_calls)}

    summary = run_browser_passes(
        "2026-03-22",
        start_pass=2,
        end_pass=3,
        session=session,
        prompt_provider=lambda as_of_date: prompts,
        ingest_func=_ingest,
    )

    assert session.open_calls == 2
    assert session.ensure_calls == 2
    assert session.submitted_prompts == ["prompt-2", "prompt-3"]
    assert [call[1] for call in ingest_calls] == [2, 3]
    assert summary["completed_passes"] == [2, 3]
    assert summary["failed_passes"] == []


def test_run_browser_passes_rejects_invalid_pass_range():
    from tradingagents.dealflow.sources.x_feed_browser_runner import run_browser_passes

    with pytest.raises(ValueError, match="start_pass must be <= end_pass"):
        run_browser_passes(
            "2026-03-22",
            start_pass=5,
            end_pass=4,
            session=object(),
            prompt_provider=lambda as_of_date: [],
            ingest_func=lambda *args, **kwargs: {},
        )


def test_browser_use_submit_prompt_pastes_then_sends():
    from tradingagents.dealflow.sources.x_feed_browser_runner import BrowserUseCLI

    events = []

    class FakeBrowser(BrowserUseCLI):
        def __init__(self):
            pass

        def state(self) -> str:
            return "[7]<div contenteditable=true />"

        def click(self, index: int):
            events.append(("click", index))

        def keys(self, keys: str):
            events.append(("keys", keys))

        def _copy_to_clipboard(self, text: str):
            events.append(("copy", text))

        def eval(self, js: str) -> str:
            if "contenteditable=true" in js or "contenteditable" in js:
                return "line one\nline two"
            return "Expert"

    browser = FakeBrowser()
    browser.submit_prompt("line one\nline two")

    assert events == [
        ("click", 7),
        ("copy", "line one\nline two"),
        ("keys", "Meta+v"),
        ("keys", "Enter"),
    ]


def test_wait_until_chat_ready_retries_until_composer_and_model_selector_exist():
    from tradingagents.dealflow.sources.x_feed_browser_runner import BrowserUseCLI

    states = [
        "Empty DOM tree (you might have to wait for the page to load)",
        "[7]<div contenteditable=true />\n[736]<button id=model-select-trigger aria-label=Model select />",
    ]

    class FakeBrowser(BrowserUseCLI):
        def __init__(self):
            pass

        def state(self) -> str:
            if len(states) > 1:
                return states.pop(0)
            return states[0]

    browser = FakeBrowser()
    ready_state = browser.wait_until_chat_ready(timeout_seconds=1, poll_interval_seconds=0)

    assert "contenteditable=true" in ready_state
    assert "id=model-select-trigger" in ready_state


def test_active_chrome_open_fresh_chat_prefers_front_active_grok_tab():
    from tradingagents.dealflow.sources.x_feed_browser_runner import ActiveChromeTabSession

    calls = []

    class FakeSession(ActiveChromeTabSession):
        def __init__(self):
            super().__init__()

        def _osascript(self, *lines: str) -> str:
            calls.append(lines)
            return "reused"

    session = FakeSession()
    session.open_fresh_chat()

    assert len(calls) == 1
    joined = "\n".join(calls[0])
    assert 'URL of active tab of front window' in joined
    assert "make new tab with properties {URL:\"https://grok.com/\"}" in joined
    assert "repeat with w in windows" not in joined


def test_active_chrome_open_fresh_chat_does_not_scan_background_tabs():
    from tradingagents.dealflow.sources.x_feed_browser_runner import ActiveChromeTabSession

    calls = []

    class FakeSession(ActiveChromeTabSession):
        def __init__(self):
            super().__init__()

        def _osascript(self, *lines: str) -> str:
            calls.append(lines)
            return "created"

    session = FakeSession()
    session.open_fresh_chat()

    assert len(calls) == 1
    joined = "\n".join(calls[0])
    assert "front window" in joined
    assert "repeat with w in windows" not in joined
    assert "repeat with i from 1 to tabCount" not in joined


def test_active_chrome_open_fresh_chat_resets_last_prompt():
    from tradingagents.dealflow.sources.x_feed_browser_runner import ActiveChromeTabSession

    class FakeSession(ActiveChromeTabSession):
        def __init__(self):
            super().__init__()

        def _osascript(self, *lines: str) -> str:
            return "reused"

    session = FakeSession()
    session._last_prompt = "old prompt"
    session.open_fresh_chat()

    assert session._last_prompt == ""


def test_active_chrome_wait_until_chat_ready_accepts_conversation_title():
    from tradingagents.dealflow.sources.x_feed_browser_runner import ActiveChromeTabSession

    class FakeSession(ActiveChromeTabSession):
        def __init__(self):
            super().__init__()

        def _js(self, script: str) -> str:
            if "document.title" in script:
                return "New conversation - Grok"
            if "window.location.href" in script:
                return "https://grok.com/c/abc123"
            if "querySelectorAll" in script:
                return "1"
            if "model-select-trigger" in script:
                return "true"
            raise AssertionError(script)

    session = FakeSession()

    assert session.wait_until_chat_ready(timeout_seconds=1, poll_interval_seconds=0) == "ready"


def test_active_chrome_wait_until_chat_ready_accepts_multiple_composers():
    from tradingagents.dealflow.sources.x_feed_browser_runner import ActiveChromeTabSession

    class FakeSession(ActiveChromeTabSession):
        def __init__(self):
            super().__init__()

        def _js(self, script: str) -> str:
            if "document.title" in script:
                return "Grok"
            if "window.location.href" in script:
                return "https://grok.com/"
            if "querySelectorAll" in script:
                return "2"
            if "model-select-trigger" in script:
                return "true"
            raise AssertionError(script)

    session = FakeSession()

    assert session.wait_until_chat_ready(timeout_seconds=1, poll_interval_seconds=0) == "ready"
