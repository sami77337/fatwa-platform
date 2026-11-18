"""Bounded observations of the existing launch, never a diagnosis or a retry."""

import math
import re
from importlib.metadata import version
from time import monotonic

from playwright.sync_api import Error as PlaywrightError

MESSAGE_LIMIT = 32_768
_PREFIX = r"^[ \t]*(?:-[ \t]+)?"


def observations():
    try:
        installed = version("playwright")
    except Exception:
        installed = "UNKNOWN"
    return {
        "schema": "fast9-launch-observations.v1",
        "playwright_version": (
            installed
            if re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", installed)
            else "UNKNOWN"
        ),
        "timeout_ms": 10_000,
        "chromium_sandbox": True,
        "driver_elapsed_ms": None,
        "launch_elapsed_ms": None,
        "launch_returned": False,
        "message_truncated": False,
        "launching_marker": "UNKNOWN",
        "launched_marker": "UNKNOWN",
        "exit_marker": "UNKNOWN",
        "exit_kind": "UNKNOWN",
        "sandbox_error_marker": "UNKNOWN",
        "loader_error_marker": "UNKNOWN",
    }


def _elapsed(start, clock):
    elapsed = (clock() - start) * 1000
    # Fixed numeric bound applies to reporting only; it does not alter a deadline.
    return min(600_000, max(0, int(elapsed))) if math.isfinite(elapsed) else None


def observe_error(error, report):
    """Read a capped existing message, emitting only reviewed fixed enums.

    Playwright call logs are not a public structured API. Missing or changed
    markers remain UNKNOWN. An exit may describe timeout cleanup, not its cause.
    """
    if not isinstance(error, PlaywrightError) or not isinstance(error.message, str):
        return
    report["message_truncated"] = len(error.message) > MESSAGE_LIMIT
    message = error.message[:MESSAGE_LIMIT]
    patterns = {
        "launching_marker": r"<launching> ",
        "launched_marker": r"<launched> pid=[0-9]{1,10}[ \t]*$",
        "sandbox_error_marker": r"\[pid=[0-9]{1,10}\]\[err\] [^\r\n]*No usable sandbox!",
        "loader_error_marker": (
            r"\[pid=[0-9]{1,10}\]\[err\] [^\r\n]*error while loading shared libraries:"
        ),
    }
    for key, pattern in patterns.items():
        if re.search(_PREFIX + pattern, message, re.MULTILINE):
            report[key] = "OBSERVED"
    exit_record = re.search(
        _PREFIX + r"\[pid=[0-9]{1,10}\] <process did exit: "
        r"exitCode=(null|-?[0-9]{1,10}), signal=(null|SIG[A-Z0-9]{1,16})>[ \t]*$",
        message,
        re.MULTILINE,
    )
    if exit_record:
        report["exit_marker"] = "OBSERVED"
        code, signal = exit_record.groups()
        report["exit_kind"] = (
            "SIGNAL"
            if signal != "null"
            else "UNKNOWN"
            if code == "null"
            else "ZERO"
            if int(code) == 0
            else "NONZERO"
        )


def launch_browser(stack, factory, executable, report, *, clock=monotonic):
    """Exactly one unchanged sandboxed 10-second launch; rethrow the same error."""
    started = clock()
    try:
        driver = stack.enter_context(factory())
    finally:
        report["driver_elapsed_ms"] = _elapsed(started, clock)
    started = clock()
    try:
        try:
            browser = driver.chromium.launch(
                executable_path=executable, chromium_sandbox=True, timeout=10_000
            )
        finally:
            report["launch_elapsed_ms"] = _elapsed(started, clock)
    except PlaywrightError as error:
        observe_error(error, report)
        raise
    else:
        report["launch_returned"] = True
        return browser
