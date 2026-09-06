"""The [+] and the [−] beside the chat panel.


Two routes and a listing. The work is all in `clones.py`; this is the surface,
and it follows the pattern `access.py` set -- `register(app)` and plain
functions, so endpoint names stay byte for byte what they were and the route
snapshot keeps its job.

WHAT THESE ROUTES REFUSE TO DECIDE
----------------------------------
Nothing here validates a name, checks a ceiling or invents a default. Every one
of those lives in `clones.py` and raises `CloneError` with a sentence a person
can act on, which this hands straight back. A route that re-implements a rule
is a second rule, and the two drift.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from flask import jsonify, redirect, request, url_for

from ... import clones as clones_module


def _back(default_endpoint: str = "chat") -> str:
    """Where to return to, from an untrusted form field.

    A single leading slash is a path on this dashboard; two is a URL somewhere
    else entirely, and `//evil.example/steal` looks relative at a glance.
    """
    back = request.form.get("back") or ""
    if not back.startswith("/") or back.startswith("//"):
        return url_for(default_endpoint)
    return back


def _wants_json() -> bool:
    return request.headers.get("Accept", "").startswith("application/json")


def _answer(message: str):
    """Say what went wrong, in the form the caller asked for."""
    if _wants_json():
        return jsonify({"ok": False, "error": message}), 400
    back = _back()
    joiner = "&" if "?" in back else "?"
    return redirect(f"{back}{joiner}trouble={quote(message)}")


def _done(**extra):
    """Say it worked, in the form the caller asked for.

    The panel asks for JSON. It used to get a redirect, which `fetch` follows
    silently to a whole HTML page -- so a refusal and a success were the same
    200 and a failed [+] simply produced no chip and nothing to read.
    """
    if _wants_json():
        return jsonify({"ok": True, **extra})
    return redirect(_back())


def register(app) -> None:
    """Attach the clone routes to the application."""

    @app.route("/clones")
    def clones_list():
        """Who is running, for the panel to draw its list.

        Dead rows are cleared first: a window somebody closed by hand should
        not keep claiming to be an agent, and finding that out on the read is
        cheaper than a timer that has to remember to run.
        """
        try:
            clones_module.forget_dead()
            rows = clones_module.listing()
        except Exception as exc:                          # noqa: BLE001
            return jsonify({"ok": False, "clones": [],
                            "error": f"{type(exc).__name__}: {exc}"})

        return jsonify({
            "ok": True,
            "main": clones_module.MAIN,
            "limit": clones_module.MAX_CLONES,
            "clones": [
                {
                    "name": one.name,
                    "folder": one.folder,
                    "created": one.created,
                    "alive": one.alive,
                }
                for one in rows
            ],
        })

    @app.route("/clones/add", methods=["POST"])
    def clones_add():
        """Make one, and start it working."""
        # Empty means "you pick" -- the usual case. A clone of David is
        # David doing a second thing, and asking somebody to invent a name for
        # that is asking them for something the system already knows.
        name = (request.form.get("name") or "").strip()             or clones_module.suggest_name()
        folder = (request.form.get("folder") or "").strip()

        if not folder:
            return _answer("A clone works somewhere — say which folder.")

        try:
            made = clones_module.create(name, Path(folder).expanduser())
        except clones_module.CloneError as exc:
            return _answer(str(exc))
        except Exception as exc:                          # noqa: BLE001
            return _answer(f"Could not start it: {exc}")

        return _done(name=made.name, folder=str(made.folder))

    @app.route("/clones/remove", methods=["POST"])
    def clones_remove():
        """Dispel one.

        Whatever it had to say has either been said into the conversation
        already or was never going to be -- there is no collecting on the way
        out, because a second silent path into shared memory is exactly what
        this design does not have.
        """
        try:
            clones_module.dispel(request.form.get("name") or "")
        except clones_module.CloneError as exc:
            return _answer(str(exc))

        return _done()
