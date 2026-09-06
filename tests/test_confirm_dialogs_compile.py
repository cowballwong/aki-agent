"""The confirm() dialogs must be JavaScript, not nearly-JavaScript.

Four Delete buttons and one on/off switch built their question by dropping a
user-typed name straight into a single-quoted JS string. Jinja escapes an
apostrophe to `&#39;` for HTML and the browser turns it back into `'` before
the JS engine sees it, so a task called "Check O'Brien's folder" produced a
syntax error. A broken `onsubmit` handler does not stop the submit: it means
the form goes through with no question asked at all. The failure is silent,
and it only ever happens to people whose names contain an apostrophe.

A sixth handler was broken differently -- a real line break inside the string
literal -- with the same consequence.

These tests parse the rendered attribute rather than looking for a filter
name, because the filter is not the point and could be replaced tomorrow.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from jinja2 import Undefined

from aki_agent.dashboard import app as dashboard_app


AWKWARD = "Check O'Brien's \"important\" folder"


def js_in(html: str) -> list[str]:
    """Every `onsubmit="..."` body, HTML-unescaped as a browser would."""
    import html as html_module

    return [html_module.unescape(one)
            for one in re.findall(r'onsubmit="([^"]*)"', html)]


def compiles(source: str) -> tuple[bool, str]:
    node = shutil.which("node")
    if not node:                                         # pragma: no cover
        pytest.skip("node is not installed here")
    done = subprocess.run([node, "--check", "-"], input=source,
                          capture_output=True, text=True)
    return done.returncode == 0, done.stderr.strip()


class AnyName(Undefined):
    """Every name in the attribute resolves to one that has broken these.

    Rendering a whole partial needs its whole context, which differs per page
    and would make this test about its fixtures rather than about the
    escaping. Each `onsubmit` is rendered alone instead, in an environment
    where anything undefined answers with the awkward name -- so the test
    covers every template in the folder, including ones written after it and
    ones whose context nobody here knows.
    """

    def __getattr__(self, name):
        if name.startswith("__"):                        # pragma: no cover
            raise AttributeError(name)
        return AWKWARD

    def __str__(self):
        return AWKWARD


@pytest.fixture
def app(tmp_path):
    made = dashboard_app.create_app(None)
    made.config["TESTING"] = True
    return made


def every_confirm_attribute():
    """(template name, the raw `onsubmit` source) for each one that asks."""
    from pathlib import Path

    from aki_agent.dashboard import app as module

    templates = Path(module.__file__).parent / "templates"
    found = []
    for path in sorted(templates.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for handler in re.findall(r'onsubmit="([^"]*)"', text, re.DOTALL):
            if "confirm(" in handler:
                found.append((path.name, handler))
    return found


def test_a_name_with_an_apostrophe_still_produces_valid_javascript(app):
    """The bug, stated as the browser experiences it."""
    handlers = every_confirm_attribute()
    assert len(handlers) >= 5, "found almost none -- the scan is broken"

    interpolating = [(name, one) for name, one in handlers if "{{" in one]
    assert interpolating, "no handler interpolates a name -- checking nothing"

    env = app.jinja_env.overlay(undefined=AnyName, autoescape=True)
    for template, handler in handlers:
        html = env.from_string(f'<form onsubmit="{handler}"></form>').render()
        for source in js_in(html):
            ok, why = compiles(source)
            assert ok, f"{template}: {source!r} does not parse: {why}"


def test_the_js_filter_escapes_what_breaks_a_single_quoted_string(app):
    """Held to the rule, not to an implementation.

    `| tojson` is the usual advice and is wrong inside a double-quoted
    attribute -- it wraps the value in double quotes, which close the
    attribute. Whatever the filter does, this is what it must achieve.
    """
    filtered = app.jinja_env.filters["js"]

    assert "'" not in filtered("O'Brien's").replace("\\'", "")
    assert "\n" not in filtered("two\nlines")
    assert filtered("back\\slash").count("\\\\") == 1
    # Plain text is left alone, so nothing already on screen changes.
    assert filtered("Weekly update") == "Weekly update"


def test_no_confirm_handler_contains_a_real_line_break():
    """A newline inside the string literal is a syntax error, served."""
    from pathlib import Path

    from aki_agent.dashboard import app as module

    templates = Path(module.__file__).parent / "templates"
    for path in sorted(templates.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for handler in re.findall(r'onsubmit="([^"]*)"', text, re.DOTALL):
            assert "\n" not in handler, (
                f"{path.name}: an onsubmit handler is split across lines, so "
                "it does not parse and the form submits unasked")
