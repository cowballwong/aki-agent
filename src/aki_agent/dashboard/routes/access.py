"""Set-up guides, and the switch that lets this be reached from outside.

WHY THE ROUTES ARE MOVING OUT OF `app.py`
-----------------------------------------
`create_app` had 120 routes and 3,200 lines
in one function, and every route was a closure over its locals -- so nothing in
it could be read, tested or imported on its own.

This is the first slice, and it is deliberately the smallest and most
self-contained one: these routes were written today, they share no helpers with
the rest, and they touch three modules nothing else uses. If the pattern is
wrong, this is the cheapest place to find out.

THE PATTERN
-----------
`register(app)` rather than a Flask blueprint. A blueprint would prefix every
endpoint name, which would rename `guide_page` to `guides.guide_page` and break
every `url_for` and the route snapshot with it. That is a rename wearing a
refactor's clothes; the point of this exercise is that the surface does not
move. Plain functions keep the endpoint names byte for byte, which is what
`tests/test_the_dashboard_surface_is_stable.py` checks.
"""

from __future__ import annotations

from flask import (abort, jsonify, redirect, render_template, request,
                   url_for)


def register(app) -> None:
    """Attach these routes to the application."""
    # -- reaching this from outside ----------------------------------------

    @app.route("/remote", methods=["POST"])
    def remote_access():
        """Open or close the one named exception to the host guard.

        A POST, so it carries the anti-forgery token like every other change.
        The banner's "turn it off" link points at the page holding the switch
        rather than at this route, for the same reason: closing this must not
        be doable by following a link somebody else made you click.

        The switch moved to Connections on 2026-08-29 (), so this comes back there and not to Settings.
        """
        from ... import exposure as exposure_module
        from ..app import back_to_connections

        if request.form.get("off"):
            _done, message = exposure_module.turn_off()
        else:
            _done, message = exposure_module.turn_on(
                request.form.get("host", ""))
        return back_to_connections(message)

    # -- set-up guides -----------------------------------------------------

    @app.route("/guides")
    def guides_index():
        """Every guide in one list.

        A page of its own rather than only links scattered beside the fields
        they explain, because the question "what do I still have to set up?"
        is asked by people who do not yet know which page the answer is on.
        """
        from ... import guides as guides_module

        return render_template("guides.html", guides=guides_module.every())

    @app.route("/guide/<topic>")
    def guide_page(topic):
        """One guide.

        `?json=1` returns the same thing as data, so a future in-page popover
        can use this route rather than growing a second copy of the text.
        """
        from ... import guides as guides_module

        found = guides_module.get(topic)
        if found is None:
            abort(404)
        if request.args.get("json"):
            return jsonify({
                "topic": found.topic,
                "title": found.title,
                "minutes": found.minutes,
                "why": found.why,
                "body": found.body(),
                "gotchas": list(found.gotchas),
                "undo": found.undo,
                "links": [list(one) for one in found.links],
            })
        return render_template("guide.html", guide=found, body=found.body())
