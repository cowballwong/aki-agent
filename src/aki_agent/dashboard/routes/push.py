"""The installable app, and the tap on the shoulder.

The maintainer chose this on 2026-09-01 as the replacement for the one thing Telegram
was doing that the dashboard could not: reaching him when he is not looking at
it. Without this the switch trades an agent that reaches you for one that waits
for you, so this is not polish -- it is what makes the change survivable.

WHY THE SERVICE WORKER IS SERVED FROM THE ROOT
----------------------------------------------
A service worker may only control pages at or below its own path. Served from
`/static/sw.js` it would control `/static/` and nothing else, and the failure
is silent -- registration succeeds, and no notification ever arrives. So it is
a route at `/sw.js`, deliberately, and the comment is here because the next
person to tidy it into the static folder will break it in a way nothing tests.

TWO THINGS THE BROWSER WILL INSIST ON, AND NEITHER IS A BUG
-----------------------------------------------------------
* A service worker registers only on a **secure origin** -- https, or
  localhost. So this works at the desk and through the tunnel, and nowhere in
  between. `exposure.py` is a dependency of this feature, not a neighbour.
* On **iOS** the page must be added to the Home Screen before it may ask for
  permission at all. That is a line in the setup guide, not something to fix.
"""

from __future__ import annotations

from flask import Response, jsonify, request

from ... import push as push_module

# Kept here rather than in a .js file because it is four handlers long and the
# route has to serve it from the root anyway. If it grows, move it -- and keep
# the route.
SERVICE_WORKER = """
// Aki's service worker. Its whole job is to turn a push into a notification
// and a tap into an open window.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) =>
  event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (error) { }

  const title = payload.title || 'Aki';
  const body = payload.body || '';
  const url = payload.url || '/';

  event.waitUntil(self.registration.showNotification(title, {
    body: body,
    icon: '/static/leaf-mark-light.png',
    badge: '/static/leaf-mark-light.png',
    // One conversation, so one notification that replaces itself rather than
    // a stack of eight the person has to clear one at a time.
    tag: 'aki-chat',
    renotify: true,
    data: { url: url },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url)
    || '/';

  // Focus the tab that is already open rather than opening a fifth one.
  event.waitUntil(self.clients.matchAll({
    type: 'window', includeUncontrolled: true,
  }).then((windows) => {
    for (const one of windows) {
      if ('focus' in one) { one.focus(); return one.navigate(target); }
    }
    if (self.clients.openWindow) return self.clients.openWindow(target);
  }));
});
""".strip()


MANIFEST = {
    "name": "Aki",
    "short_name": "Aki",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#1f2933",
    "icons": [
        {"src": "/static/leaf-mark-light.png", "sizes": "512x512",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/leaf-mark-dark.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ],
}


def register(app) -> None:
    """Attach the app-install and notification routes."""

    @app.route("/manifest.webmanifest")
    def web_manifest():
        return Response(
            __import__("json").dumps(MANIFEST),
            mimetype="application/manifest+json")

    @app.route("/sw.js")
    def service_worker():
        response = Response(SERVICE_WORKER, mimetype="application/javascript")
        # A stale worker is a worker that stops delivering after an upgrade
        # and gives no sign of it.
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.route("/push/key")
    def push_key():
        """What the browser needs to subscribe. A public key, published."""
        if not push_module.available():
            return jsonify({
                "ok": False,
                "error": ("Notifications need one extra piece. Install it "
                          "with:  pip install aki-agent[push]"),
            })
        try:
            return jsonify({"ok": True, "key": push_module.public_key()})
        except push_module.PushUnavailable as exc:
            return jsonify({"ok": False, "error": str(exc)})

    @app.route("/push/subscribe", methods=["POST"])
    def push_subscribe():
        """Remember this browser."""
        raw = request.get_json(silent=True) or {}
        try:
            push_module.subscribe(raw.get("subscription") or raw,
                                  label=str(raw.get("label") or ""))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:                          # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True,
                        "devices": len(push_module.listing())})

    @app.route("/push/unsubscribe", methods=["POST"])
    def push_unsubscribe():
        raw = request.get_json(silent=True) or {}
        endpoint = str(raw.get("endpoint") or "")
        return jsonify({"ok": True,
                        "forgotten": push_module.unsubscribe(endpoint)})

    @app.route("/push/test", methods=["POST"])
    def push_test():
        """Prove it works, from the machine, before trusting it with anything.

        A notification setup that is only exercised by a real alert at 07:30 is
        one that gets discovered broken at 07:30.
        """
        try:
            result = push_module.send(
                "Aki", "Notifications are working.", url="/")
        except push_module.PushUnavailable as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:                          # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True, **result})
