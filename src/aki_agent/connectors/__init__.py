"""Connecting the assistant to the user's mail, files and calendar.

THE CONSTRAINT THAT SHAPES ALL OF THIS
--------------------------------------
This package promises: no API key, no developer account, no server, install in
one command. Everything here has to keep that promise.

That rules out the obvious approach. The Gmail API, the Google Drive API and
the Dropbox API all require an OAuth application to be registered, which means
either the student registers a developer app (which they will not do) or the
package ships a client secret (which would be a credential committed in
source, the exact defect being corrected elsewhere in this codebase).

So each connector takes the route that needs no application registration:

    MAIL      IMAP and SMTP with an app password.
              Works with Gmail, Yahoo, Outlook/Hotmail, iCloud, Fastmail and
              any other IMAP host. Standard library only.

    FILES     The sync folder that is already on the machine.
              Google Drive, Dropbox, OneDrive and iCloud Drive all put a real
              folder on disk. Reading that folder needs no API at all, works
              offline, and is faster than any of their APIs.

    CALENDAR  ICS subscription URLs, and local .ics files.
              Every calendar service publishes these. Read-only.

WHAT THIS DELIBERATELY DOES NOT DO, AND WHY IT IS SAID OUT LOUD
---------------------------------------------------------------
    * It cannot create or move a calendar event. ICS is read-only.
    * It cannot see files stored only in the cloud and never synced.
    * It cannot use provider-specific features -- Gmail labels, Drive
      comments, Dropbox sharing.

Each of those needs OAuth, and OAuth needs a registered application. That is a
real limit, not an oversight, and it belongs in front of the user rather than
discovered later.
"""

from . import calendars, files, mail  # noqa: F401

__all__ = ["mail", "files", "calendars"]
