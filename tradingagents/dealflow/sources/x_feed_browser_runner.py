"""Deterministic browser runner for the manual X-feed workflow."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


_RESPONSE_INDEX_RE = re.compile(r"\[(\d+)\]<li level=1 />")
_COMPOSER_INDEX_RE = re.compile(r"\[(\d+)\]<div contenteditable=true />")
_INDEX_LINE_RE = re.compile(r"\[(\d+)\]<")


def extract_last_response_index(state_text: str) -> Optional[int]:
    indices = [int(match.group(1)) for match in _RESPONSE_INDEX_RE.finditer(str(state_text or ""))]
    if not indices:
        return None
    return max(indices)


def extract_composer_index(state_text: str) -> Optional[int]:
    match = _COMPOSER_INDEX_RE.search(str(state_text or ""))
    if not match:
        return None
    return int(match.group(1))


def extract_index_for_text(state_text: str, needle: str) -> Optional[int]:
    lines = str(state_text or "").splitlines()
    for idx, line in enumerate(lines):
        if needle not in line:
            continue
        for back in range(idx, max(-1, idx - 8), -1):
            prev = lines[back]
            match = _INDEX_LINE_RE.search(prev)
            if match:
                return int(match.group(1))
    return None


def normalize_browser_text(text: str) -> str:
    normalized = str(text or "").replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def extract_response_region(main_text: str, prompt_text: str) -> str:
    text = normalize_browser_text(main_text)
    prompt = normalize_browser_text(prompt_text)
    if prompt and prompt in text:
        text = text.split(prompt, 1)[1]
    text = text.lstrip()

    thought_matches = list(re.finditer(r"Thought for [^\n]+", text))
    if thought_matches:
        text = text[thought_matches[-1].end():].lstrip()
    return text.strip()


def prompts_match_for_submission(expected: str, actual: str) -> bool:
    def _compress(text: str) -> str:
        lines = [line.strip() for line in normalize_browser_text(text).splitlines() if line.strip()]
        return "\n".join(lines)

    return _compress(expected) == _compress(actual)


class BrowserUseCLI:
    def __init__(self, *, profile: str = "Default", session_name: str = "default"):
        self.profile = str(profile or "Default").strip() or "Default"
        self.session_name = str(session_name or "default").strip() or "default"
        self.binary = shutil.which("browser-use")
        if not self.binary:
            raise RuntimeError("browser-use is not installed or not on PATH")

    def _run(self, args: Sequence[str]) -> str:
        command = [self.binary, "--session", self.session_name, *args]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip() or f"browser-use failed: {' '.join(args)}"
            raise RuntimeError(message)
        return proc.stdout.strip()

    def open_fresh_chat(self):
        self._run(["-b", "real", "--profile", self.profile, "--headed", "open", "https://grok.com"])

    def wait_until_chat_ready(
        self,
        *,
        timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
    ) -> str:
        deadline = time.time() + max(1, int(timeout_seconds))
        while time.time() < deadline:
            state = self.state()
            if "Empty DOM tree" in state:
                time.sleep(poll_interval_seconds)
                continue
            if extract_composer_index(state) is not None and "id=model-select-trigger" in state:
                return state
            time.sleep(poll_interval_seconds)
        raise TimeoutError("Timed out waiting for Grok chat to become ready")

    def state(self) -> str:
        return self._run(["state"])

    def click(self, index: int):
        self._run(["click", str(index)])

    def input(self, index: int, text: str):
        self._run(["input", str(index), text])

    def keys(self, keys: str):
        self._run(["keys", keys])

    def get_text(self, index: int) -> str:
        output = self._run(["get", "text", str(index)])
        if "text:" not in output:
            return normalize_browser_text(output)
        _, text = output.split("text:", 1)
        return normalize_browser_text(text)

    def eval(self, js: str) -> str:
        output = self._run(["eval", js])
        if "result:" not in output:
            return normalize_browser_text(output)
        _, result = output.split("result:", 1)
        return normalize_browser_text(result)

    def _copy_to_clipboard(self, text: str):
        proc = subprocess.run(["pbcopy"], input=text, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip() or "pbcopy failed"
            raise RuntimeError(message)

    def _composer_text(self) -> str:
        return normalize_browser_text(
            self.eval(
                "(() => { "
                "const nodes = Array.from(document.querySelectorAll('[contenteditable=\"true\"]')); "
                "const active = nodes.find((el) => el && el.offsetParent !== null) || nodes[0]; "
                "return (active?.innerText || '').trim();"
                " })()"
            )
        )

    def ensure_expert(self):
        current = self.eval(
            "(() => { const el = document.getElementById('model-select-trigger'); return (el?.innerText || '').trim(); })()"
        )
        if current == "Expert":
            return

        state = self.state()
        trigger_index = extract_index_for_text(state, "id=model-select-trigger")
        if trigger_index is None:
            raise RuntimeError("Could not find Grok model selector")
        self.click(trigger_index)

        time.sleep(0.5)
        menu_state = self.state()
        expert_index = extract_index_for_text(menu_state, "Expert")
        if expert_index is None:
            raise RuntimeError("Could not find Expert mode in Grok model menu")
        self.click(expert_index)

        time.sleep(0.5)
        confirmed = self.eval(
            "(() => { const el = document.getElementById('model-select-trigger'); return (el?.innerText || '').trim(); })()"
        )
        if confirmed != "Expert":
            raise RuntimeError(f"Grok model selector did not switch to Expert (current={confirmed!r})")

    def submit_prompt(self, prompt: str):
        state = self.state()
        composer_index = extract_composer_index(state)
        if composer_index is None:
            raise RuntimeError("Could not find Grok composer")
        normalized_prompt = normalize_browser_text(prompt)
        self.click(composer_index)
        self._copy_to_clipboard(prompt)
        self.keys("Meta+v")
        time.sleep(0.25)
        pasted = self._composer_text()
        if pasted != normalized_prompt:
            self.keys("Control+v")
            time.sleep(0.25)
            pasted = self._composer_text()
        if pasted != normalized_prompt:
            raise RuntimeError("Prompt paste verification failed in Grok composer")
        self.keys("Enter")

    def wait_for_response_text(
        self,
        *,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
        stable_reads_required: int = 2,
    ) -> str:
        deadline = time.time() + max(1, int(timeout_seconds))
        last_text = ""
        stable_reads = 0

        while time.time() < deadline:
            state = self.state()
            response_index = extract_last_response_index(state)
            if response_index is None:
                time.sleep(poll_interval_seconds)
                continue

            response_text = self.get_text(response_index)
            if not response_text:
                time.sleep(poll_interval_seconds)
                continue

            if response_text == last_text:
                stable_reads += 1
            else:
                last_text = response_text
                stable_reads = 1

            if stable_reads >= max(1, int(stable_reads_required)):
                return response_text

            time.sleep(poll_interval_seconds)

        raise TimeoutError("Timed out waiting for Grok response to stabilize")


class ActiveChromeTabSession:
    def __init__(self, *, profile: str = "Default", session_name: str = "default"):
        self.profile = str(profile or "Default").strip() or "Default"
        self.session_name = str(session_name or "default").strip() or "default"
        self._last_prompt = ""

    def _run(self, args: Sequence[str], *, input_text: Optional[str] = None) -> str:
        proc = subprocess.run(
            list(args),
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip() or f"Command failed: {' '.join(args)}"
            raise RuntimeError(message)
        return (proc.stdout or "").strip()

    def _osascript(self, *lines: str) -> str:
        args = ["osascript"]
        for line in lines:
            args.extend(["-e", line])
        return self._run(args)

    def _js(self, script: str) -> str:
        line = f'tell application "Google Chrome" to execute active tab of front window javascript {json.dumps(script)}'
        return self._osascript(line)

    def _copy_to_clipboard(self, text: str):
        self._run(["pbcopy"], input_text=text)

    def _activate_chrome(self):
        self._osascript('tell application "Google Chrome" to activate')

    @staticmethod
    def _screen_point_from_rect(payload: Dict[str, Any]) -> Tuple[float, float]:
        rect = dict(payload.get("rect") or {})
        screen_x = float(payload.get("screenX", 0.0) or 0.0)
        screen_y = float(payload.get("screenY", 0.0) or 0.0)
        outer_height = float(payload.get("outerHeight", 0.0) or 0.0)
        inner_height = float(payload.get("innerHeight", 0.0) or 0.0)
        viewport_x = float(rect.get("left", 0.0) or 0.0) + (float(rect.get("width", 0.0) or 0.0) / 2.0)
        viewport_y = float(rect.get("top", 0.0) or 0.0) + (float(rect.get("height", 0.0) or 0.0) / 2.0)
        chrome_top = screen_y + (outer_height - inner_height)
        return screen_x + viewport_x, chrome_top + viewport_y

    def _swift_click(self, screen_x: float, screen_y: float):
        script = (
            "import Foundation\n"
            "import ApplicationServices\n"
            "Thread.sleep(forTimeInterval: 0.2)\n"
            f"let p = CGPoint(x: {screen_x}, y: {screen_y})\n"
            "if let move = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left), "
            "let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left), "
            "let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left) { "
            "move.post(tap: .cghidEventTap); down.post(tap: .cghidEventTap); up.post(tap: .cghidEventTap); print(\"clicked\") "
            "} else { print(\"failed\") }"
        )
        self._run(["swift", "-e", script])

    def _system_keystroke(self, key: str, *, command: bool = False, key_code: Optional[int] = None):
        lines = ['tell application "Google Chrome" to activate']
        if key_code is not None:
            lines.append(f'tell application "System Events" to key code {int(key_code)}')
        elif command:
            lines.append(f'tell application "System Events" to keystroke {json.dumps(key)} using command down')
        else:
            lines.append(f'tell application "System Events" to keystroke {json.dumps(key)}')
        self._osascript(*lines)

    def _json(self, script: str) -> Dict[str, Any]:
        raw = self._js(script)
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}

    def _model_text(self) -> str:
        return normalize_browser_text(
            self._js("document.getElementById('model-select-trigger')?.innerText || ''")
        )

    def _composer_text(self) -> str:
        return normalize_browser_text(
            self._js(
                "(() => { "
                "const el = document.querySelector('[contenteditable=\"true\"], textarea[aria-label=\"Ask Grok anything\"]'); "
                "if (!el) return ''; "
                "return (typeof el.value === 'string' ? el.value : el.innerText) || '';"
                "})()"
            )
        )

    def _main_text(self) -> str:
        return normalize_browser_text(self._js("document.querySelector('main')?.innerText || ''"))

    def open_fresh_chat(self):
        self._osascript(
            'tell application "Google Chrome"',
            'activate',
            'if (count of windows) = 0 then',
            'make new window',
            'set URL of active tab of front window to "https://grok.com/"',
            'return "created"',
            'end if',
            'set tabUrl to URL of active tab of front window',
            'if tabUrl starts with "https://grok.com" then',
            'set index of front window to 1',
            'return "reused"',
            'end if',
            'tell front window to make new tab with properties {URL:"https://grok.com/"}',
            'return "created"',
            'end tell',
        )
        self._last_prompt = ""

    def wait_until_chat_ready(
        self,
        *,
        timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
    ) -> str:
        deadline = time.time() + max(1, int(timeout_seconds))
        while time.time() < deadline:
            title = normalize_browser_text(self._js("document.title || ''"))
            href = normalize_browser_text(self._js("window.location.href || ''"))
            composers = normalize_browser_text(
                self._js("document.querySelectorAll('[contenteditable=true], textarea[aria-label=\"Ask Grok anything\"]').length.toString()")
            )
            selector_present = normalize_browser_text(
                self._js("document.getElementById('model-select-trigger') ? 'true' : 'false'")
            )
            try:
                composer_count = int(composers)
            except (TypeError, ValueError):
                composer_count = 0
            title_ready = "Grok" in title
            if title_ready and href.startswith("https://grok.com") and composer_count >= 1 and selector_present == "true":
                return "ready"
            time.sleep(poll_interval_seconds)
        raise TimeoutError("Timed out waiting for Grok chat to become ready")

    def ensure_expert(self):
        if self._model_text() == "Expert":
            return

        geometry = self._json(
            "(() => { const el = document.getElementById('model-select-trigger'); "
            "if (!el) return JSON.stringify({}); "
            "const r = el.getBoundingClientRect(); "
            "return JSON.stringify({screenX: window.screenX, screenY: window.screenY, outerHeight: window.outerHeight, innerHeight: window.innerHeight, rect:{left:r.left, top:r.top, width:r.width, height:r.height}}); })()"
        )
        if not geometry.get("rect"):
            raise RuntimeError("Could not locate Grok model selector")

        screen_x, screen_y = self._screen_point_from_rect(geometry)
        self._activate_chrome()
        self._swift_click(screen_x, screen_y)

        deadline = time.time() + 5
        while time.time() < deadline:
            state = self._json(
                "(() => { const el = document.getElementById('model-select-trigger'); "
                "return JSON.stringify({state: el?.getAttribute('data-state') || '', expanded: el?.getAttribute('aria-expanded') || ''}); })()"
            )
            if state.get("state") == "open" and state.get("expanded") == "true":
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Could not open Grok model selector")

        clicked = normalize_browser_text(
            self._js(
                "(() => { "
                "const model = document.getElementById('model-select-trigger'); "
                "if (!model) return 'MISSING'; "
                "const r = model.getBoundingClientRect(); "
                "const xs = [r.left + 16, r.left + r.width / 2, r.right - 16]; "
                "const ys = [r.bottom + 20, r.bottom + 60, r.bottom + 100, r.bottom + 140, r.bottom + 180]; "
                "for (const y of ys) { "
                "  for (const x of xs) { "
                "    const el = document.elementFromPoint(x, y); "
                "    const text = (el?.innerText || '').trim(); "
                "    if (text.includes('Expert') || text.includes('Thinks hard')) { el.click(); return text; } "
                "  } "
                "} "
                "return 'MISSING';"
                "})()"
            )
        )
        if "Expert" not in clicked and "Thinks hard" not in clicked:
            raise RuntimeError("Could not select Expert mode in Grok")

        deadline = time.time() + 5
        while time.time() < deadline:
            if self._model_text() == "Expert":
                return
            time.sleep(0.25)
        raise RuntimeError(f"Grok model selector did not switch to Expert (current={self._model_text()!r})")

    def submit_prompt(self, prompt: str):
        focused = normalize_browser_text(
            self._js(
                "(() => { const el = document.querySelector('[contenteditable=\"true\"], textarea[aria-label=\"Ask Grok anything\"]'); "
                "if (!el) return 'missing'; el.focus(); return document.activeElement === el ? 'focused' : 'not-focused'; })()"
            )
        )
        if focused != "focused":
            raise RuntimeError("Could not focus Grok composer")

        normalized_prompt = normalize_browser_text(prompt)
        self._copy_to_clipboard(prompt)
        self._system_keystroke("v", command=True)
        time.sleep(0.4)

        pasted = self._composer_text()
        if not prompts_match_for_submission(normalized_prompt, pasted):
            raise RuntimeError("Prompt paste verification failed in Grok composer")
        self._last_prompt = normalized_prompt
        self._system_keystroke("", key_code=36)

    def wait_for_response_text(
        self,
        *,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
        stable_reads_required: int = 2,
    ) -> str:
        from tradingagents.dealflow.sources.x_feed_scout import _extract_json_payload

        deadline = time.time() + max(1, int(timeout_seconds))
        last_text = ""
        stable_reads = 0

        while time.time() < deadline:
            main_text = self._main_text()
            candidate = extract_response_region(main_text, self._last_prompt)
            parsed = _extract_json_payload(candidate) if candidate else None
            if not isinstance(parsed, dict):
                time.sleep(poll_interval_seconds)
                continue

            if candidate == last_text:
                stable_reads += 1
            else:
                last_text = candidate
                stable_reads = 1

            if stable_reads >= max(1, int(stable_reads_required)):
                return candidate
            time.sleep(poll_interval_seconds)

        raise TimeoutError("Timed out waiting for Grok response to stabilize")


def run_browser_passes(
    as_of_date: str,
    *,
    start_pass: int = 1,
    end_pass: int = 16,
    profile: str = "Default",
    dry_run: bool = False,
    session: Any | None = None,
    prompt_provider: Optional[Callable[[str], List[Tuple[int, str, str]]]] = None,
    ingest_func: Optional[Callable[[str, str, int, bool], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    from tradingagents.dealflow.sources.x_feed_manual import finalize_x_feed, generate_prompts, get_readiness, ingest_pass

    prompt_provider = prompt_provider or generate_prompts
    ingest_func = ingest_func or ingest_pass

    if int(start_pass) > int(end_pass):
        raise ValueError("start_pass must be <= end_pass")

    def _prompt_map() -> Dict[int, Tuple[str, str]]:
        prompts = list(prompt_provider(as_of_date))
        return {int(pass_num): (label, prompt) for pass_num, label, prompt in prompts}

    prompt_map = _prompt_map()
    available_passes = sorted(prompt_map.keys())
    if not available_passes:
        raise RuntimeError("No X-feed prompts available")

    min_pass = min(available_passes)
    max_pass = max(available_passes)
    if int(start_pass) < min_pass or int(end_pass) > max_pass:
        raise ValueError(f"pass range must be within {min_pass}-{max_pass}")

    browser = session or ActiveChromeTabSession(
        profile=profile,
        session_name=f"xfeed-{int(time.time() * 1000)}",
    )
    results: List[Dict[str, Any]] = []
    completed_passes: List[int] = []

    for pass_num in range(int(start_pass), int(end_pass) + 1):
        prompt_map = _prompt_map()
        if pass_num not in prompt_map:
            raise ValueError(f"Pass {pass_num} is not defined")
        _, prompt = prompt_map[pass_num]

        browser.open_fresh_chat()
        browser.wait_until_chat_ready()
        browser.ensure_expert()
        browser.submit_prompt(prompt)
        raw_text = browser.wait_for_response_text()
        result = ingest_func(as_of_date, raw_text, pass_num, dry_run=dry_run)
        results.append(dict(result or {}))
        completed_passes.append(pass_num)

    readiness = {}
    final_manifest = {}
    if not dry_run:
        final_manifest = dict(finalize_x_feed(as_of_date))
        readiness = dict(get_readiness(as_of_date))

    return {
        "date": as_of_date,
        "start_pass": int(start_pass),
        "end_pass": int(end_pass),
        "completed_passes": completed_passes,
        "failed_passes": [],
        "results": results,
        "readiness": readiness,
        "final_manifest": final_manifest,
        "dry_run": bool(dry_run),
    }
