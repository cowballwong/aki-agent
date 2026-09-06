"""The left rail, in one definition.

Twenty flat entries became six groups.

THE COST OF GROUPING, AND THE THREE THINGS THAT PAY IT BACK
-----------------------------------------------------------
Grouping makes a deep page take two clicks instead of one. That is a real
loss, and it is why most reorganised menus feel worse than the mess they
replaced. Three decisions pay it back, and none of them is decoration:

  * **No address changes.** `/skills` is still `/skills`. Grouping adds a tab
    strip; it does not move anything. Nothing anybody bookmarked breaks.
  * **Each group remembers the tab you were last on** (in the browser, in
    `localStorage`). That is what turns the second click back into a first
    one for the page a person actually uses.
  * **Counts roll up.** "3 waiting" appears next to Work, not only on the
    page inside it -- a badge you have to open a group to see is a badge that
    does not work.

One definition, used by the rail and by the tab strip, because two would
disagree the first time a page moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Page:
    path: str
    label: str
    # Which shared count belongs on this page, if any.
    badge: str = ""
    # Extra path prefixes that belong to this page -- an item page is part of
    # the work, and the rail should stay lit while you are reading one.
    also: tuple = ()


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    icon: str
    pages: tuple = field(default_factory=tuple)

    def owns(self, path: str) -> bool:
        return any(page.path == path or path.startswith(page.path.rstrip("/") + "/")
                   or any(path.startswith(prefix) for prefix in page.also)
                   for page in self.pages if page.path != "/")

    def count(self, counts: dict) -> int:
        """The number on the group.

        A page may name more than one count, comma-separated. Inbox needed
        it: it held both the decisions waiting and the messages held back, and
        a badge showing only one of them would send somebody to a page with
        more on it than the number promised — which is worse than no number.

        **Nothing declares a badge as of 2026-08-23.** Inbox was the last
        page that did and it left the rail; the counts it carried are now the
        three queue buttons on Today, which say what kind each number is
        rather than adding them into one. This is kept rather than deleted
        because it is one word per page to use and costs nothing while
        unused — but it is an empty facility, not a working feature, and a
        badge appearing anywhere means somebody wired it up on purpose.
        """
        total = 0
        for page in self.pages:
            for key in (page.badge or "").split(","):
                key = key.strip()
                if key:
                    total += int(counts.get(key) or 0)
        return total


GROUPS = (
    # Grouped by the question somebody is asking, not by what the thing is
    # made of. reported 2026-08-21, having been offered a reordering: "in
    # fact....i found that the side bar item grouping is not very user
    # friendly.... I Want you to redesign!!!! Not just moving page, but really
    # think what to put in a page".
    #
    # Reading every template first turned up five outright duplications: the
    # working-state panel drawn on two pages, one colour field with two
    # editors, one quiet-hours form on two pages, one "where secrets live"
    # card at the foot of two pages, and a Library whose on-switch writes into
    # the very stores the next two pages list. Twenty-three pages, and a good
    # number of them a single read-only table.
    #
    # So this is fifteen, and nothing was dropped — the merged pages are
    # composed from the same template pieces, unedited.
    Group("today", "Today", "\u2600", (
        Page("/", "Today"),
    )),
    Group("work", "Workspace", "\u25a4", (
        Page("/projects", "Workspace", also=("/item", "/workspace")),
    )),
    # Inbox left the rail on 2026-08-23. The maintainer: \u300cside bar \u5605 INBOX button \u5df2\u7d93
    # \u5514\u518d\u9700\u8981\uff0c\u56e0\u70ba\u6211\u5730\u6709 action, wait, draft button.\u300d The three queue buttons
    # on Today open the same items split by whose move it is, which is a
    # distinction one Inbox could never draw. The page itself still renders
    # and both of its addresses still answer -- see MOVED below.
    Group("abilities", "Abilities", "\u2726", (
        # Schedule leads.
        # It is also the only page in this group that changes what the agent
        # does while nobody is watching; the other three are things it can
        # reach when asked. What acts on its own goes first.
        Page("/schedule", "Schedule"),
        # TOOLS, and the Library is inside it. reported 2026-09-05:
        #
        # They were two tabs answering one question. The Library is where an
        # ability comes FROM and Yours is where it ends up -- and since
        # adding one from the Library puts it straight into these lists, the
        # two pages were already halves of the same act.
        #
        # THE ADDRESS STAYS `/yours`. `/tools` is already the API-keys page
        # under System, and taking that name would either collide or mean
        # moving a page nobody asked to move. The label is what people read;
        # the address is what old links and bookmarks use.
        #
        # Skills and specialists were split because one is a folder and the
        # other is a JSON record. That is a storage detail, not a difference
        # anybody using it would draw.
        Page("/yours", "Tools",
             also=("/skills", "/specialists", "/library", "/library/")),
        Page("/knowledge", "Knowledge", also=("/learned",)),
        # Workflows joined this group on 2026-08-29. A workflow answers "what
        # whole jobs can this do", which is the same question the rest of this
        # group answers -- not "what else can it reach", which is Keys &
        # servers, where plugins live.
        Page("/workflows", "Workflows"),
    )),
    Group("system", "System", "\u25c9", (
        Page("/health", "Health"),
        Page("/connections", "Connections", also=("/guides", "/guide")),
        # Keys and MCP servers both answer "what else can it reach".
        Page("/keys", "Keys & servers", also=("/tools", "/mcp")),
        # Now, and then. The old split was by data source — five pages for
        # two questions.
        Page("/running", "Running", also=("/watching", "/sessions")),
        # MEMORY, not History.
        #
        # It had grown past its name. Two accounts of what happened is a
        # history; the same page with reflection and a vector store in it is
        # the assistant's memory, and the tabs underneath are its parts.
        #
        # `/memory` is the address it is linked by, and `/history` still
        # answers -- one endpoint, two rules. Every earlier note, guide and
        # bookmark points at the old one.
        Page("/memory", "Memory",
             also=("/history", "/activity", "/events", "/logs")),
        # Out on its own for two days, now a tab in here. reported 2026-08-23:
        # -- and, in the same breath, that the badge should go with it:
        # He is right. A count on a page of rules is a count of something the
        # page cannot help you with.
        Page("/notifications", "Notifications"),
    )),
    # and on 2026-08-29 the two names swapped places: /.
    #
    # It reads better this way round. The rail answers "where do I go to
    # change something", which is the word everybody already looks for. The
    # page inside it is the one about who you are, who it is, and what you
    # two have agreed -- which is not the machine's settings at all.
    Group("settings", "Settings", "\u2699", (
        Page("/settings", "You and Me"),
        # Its own page again (reported 2026-08-21): a theme is now a
        # whole look rather than a colour field, and the rail links
        # straight to it.
        Page("/theme", "Theme"),
        # These two spent a paragraph each explaining they were not the other.
        Page("/rules", "Rules & limits", also=("/safety",)),
    )),
)


# Where each old page's CONTENT now lives.
#
# The old routes are deliberately still registered and still render -- nothing
# was deleted, so no bookmark breaks and no URL 404s. What changed is that the
# rail no longer offers them, because the same content is now a section of the
# page named here. This table is the record of that, and the canary test reads
# it to check every old page has somewhere to have gone.
MOVED = {
    # Both land on Today, where the three queue buttons open these items.
    "/inbox": "/",
    "/waiting": "/",
    "/skills": "/yours",
    "/specialists": "/yours",
    "/learned": "/knowledge",
    "/watching": "/running",
    "/sessions": "/running",
    # These three pointed at "/history" until 2026-09-05. The page is
    # `/memory` now and `/history` is one of its `also` paths -- which is
    # exactly what this table must NOT contain, since the canary checks that
    # the destination is a page in the rail.
    "/activity": "/memory",
    "/events": "/memory",
    # `/chat` is gone entirely as of 2026-09-04, not moved. The maintainer removed the
    # chat panel from the dashboard — — and this page was the same conversation grouped by day.
    # Left out of this table on purpose: a redirect would say the feature is
    # somewhere else, and it is not anywhere.
    "/logs": "/memory",
    "/tools": "/keys",
    "/mcp": "/keys",
    "/safety": "/rules",
}


def current(path: str, groups: tuple | None = None) -> Group:
    """Which group the person is in. Today is the fallback, as the home.

    `groups` exists so the tab strip is drawn from the *same* renamed groups
    as the rail. Drawing it from the module constant instead left the
    architect's word on a music teacher's tabs -- the leak the rail had just
    been fixed for, one element over.
    """
    groups = groups or GROUPS
    for group in groups:
        if group.owns(path):
            return group
    return groups[0]


def every_path() -> list[str]:
    """Every address the rail can reach -- for the test that none 404s."""
    return [page.path for group in GROUPS for page in group.pages]

def for_label(plural: str) -> tuple:
    """The groups, with the work page named in the user's own word.

    THE RULE THIS EXISTS FOR
    ------------------------
    No profession-specific word may appear in shared chrome. The first
    version of this file hardcoded "Projects" in the rail, and a music
    teacher's dashboard would have said "Projects" on every page -- caught by
    the canary test that reads both example configurations and fails if
    either one's vocabulary appears in the other's pages.
    """
    if not plural:
        return GROUPS

    # Nothing is renamed any more, and the reason is worth keeping.
    #
    # This used to put the user's own word ("Projects", "Students") on the
    # /projects tab, because the tab led to a list of those things. It now
    # leads to the list of *workspaces*, and "workspace" is this package's
    # word rather than any profession's -- so the leak this function was
    # written to prevent cannot happen through it.
    #
    # The function stays, with its signature, because the canary test that
    # reads both example configurations calls it. An empty implementation
    # that still answers is better than a caller hunting for one that went.
    return GROUPS
