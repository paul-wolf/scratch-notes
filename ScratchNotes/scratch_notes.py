"""Notes that behave like unsaved tabs but are plain files.

A new note is a tab that already has a file name in the notes folder; it is
written to disk shortly after each pause in typing, so there is never anything
to name or save. Every file under the notes folder is autosaved the same way.
"""
import hashlib
import json
import math
import os
import re
import time

import sublime
import sublime_plugin

SETTINGS = "ScratchNotes.sublime-settings"
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{6}\.md$")
NOTE_EXTENSIONS = (".md", ".markdown", ".txt")
SKIP_DIRS = {".obsidian", ".trash", ".git"}


def setting(key):
    return sublime.load_settings(SETTINGS).get(key)


def notes_dir():
    return os.path.realpath(os.path.expanduser(setting("notes_dir")))


def inbox_dir():
    return os.path.join(notes_dir(), setting("inbox"))


def is_note(view):
    name = view.file_name()
    return bool(name) and os.path.realpath(name).startswith(notes_dir() + os.sep)


def apply_view_settings(view):
    """Obsidian-like wrapping, for notes only."""
    if is_note(view):
        for key, value in (setting("view_settings") or {}).items():
            view.settings().set(key, value)


def new_note(window, text=""):
    os.makedirs(inbox_dir(), exist_ok=True)
    path = os.path.join(inbox_dir(), time.strftime("%Y-%m-%d %H%M%S") + ".md")
    view = window.new_file(syntax="Packages/Markdown/Markdown.sublime-syntax")
    # Give the tab its file name without creating the file: an untouched note leaves nothing behind.
    view.retarget(path)
    apply_view_settings(view)
    if text:
        view.run_command("append", {"characters": text})
        view.run_command("save")
    return view


def slug(text):
    """File-name words from the first line that has any."""
    for line in text.splitlines():
        words = re.findall(r"\w+", line)
        if words:
            return " ".join(words)[:60].strip()
    return ""


# --- Activity: which notes get opened and edited, and when ------------------

ACTIVITY_LOG = os.path.expanduser("~/Library/Application Support/ScratchNotes/activity.jsonl")
HALFLIFE_DAYS = 14.0
WEIGHTS = {"edit": 2.0, "open": 1.0}
LOG_EVERY = 600  # seconds between two entries of the same kind for one note
_last_logged = {}


def log_activity(kind, path, **extra):
    """Append one line per event; repeats within LOG_EVERY are dropped."""
    now = time.time()
    if kind in WEIGHTS:
        if now - _last_logged.get((kind, path), 0) < LOG_EVERY:
            return
        _last_logged[(kind, path)] = now
    try:
        os.makedirs(os.path.dirname(ACTIVITY_LOG), exist_ok=True)
        with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(t=int(now), kind=kind, path=path, **extra)) + "\n")
    except OSError:
        pass


def activity_scores():
    """Frecency per note path: each event counts for less as it ages."""
    scores, now = {}, time.time()
    try:
        with open(ACTIVITY_LOG, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return scores
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        path = event.get("path")
        if event.get("kind") == "rename":
            # Carry the history over to the new name.
            scores[event["to"]] = scores.get(event["to"], 0) + scores.pop(path, 0)
        elif event.get("kind") in WEIGHTS:
            age_days = (now - event["t"]) / 86400
            scores[path] = scores.get(path, 0) + WEIGHTS[event["kind"]] * math.exp(-age_days / HALFLIFE_DAYS)
    return scores


def recency(mtime):
    """Edits made anywhere, Obsidian included, show up as the file's modified time."""
    return WEIGHTS["edit"] * math.exp(-(time.time() - mtime) / 86400 / HALFLIFE_DAYS)


def ago(mtime):
    seconds = time.time() - mtime
    for size, unit in ((86400 * 365, "y"), (86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return "{}{} ago".format(int(seconds // size), unit)
    return "just now"


def plugin_loaded():
    for window in sublime.windows():
        for view in window.views():
            apply_view_settings(view)


class ScratchNewNoteCommand(sublime_plugin.WindowCommand):
    def run(self):
        new_note(self.window)


class ScratchAdoptTabsCommand(sublime_plugin.WindowCommand):
    """Turn every unsaved tab, in all windows, into a note file in place.

    A tab that sublime_export.py already exported takes over that file, so
    there is one copy, not two; any other goes to a new file beside them.
    """

    def run(self):
        folder = os.path.join(notes_dir(), setting("adopt_dir"))
        os.makedirs(folder, exist_ok=True)
        exported = {}
        for name in os.listdir(folder):
            match = re.search(r"-([0-9a-f]{10})\.md$", name)
            if match:
                exported[match.group(1)] = name
        adopted = 0
        for window in sublime.windows():
            for view in window.views():
                if view.file_name() or view.is_scratch() or view.is_loading():
                    continue
                text = view.substr(sublime.Region(0, view.size()))
                if not text.strip():
                    continue
                digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
                old = exported.pop(digest, None)
                # Drop the hash from the name: the exporter then leaves the file alone.
                title = old[:-14] if old else (slug(view.name() + "\n" + text) or "untitled")
                path = os.path.join(folder, title + ".md")
                n = 2
                while os.path.exists(path):
                    path = os.path.join(folder, "{} {}.md".format(title, n))
                    n += 1
                if old:
                    os.rename(os.path.join(folder, old), path)
                view.retarget(path)
                view.run_command("save")
                apply_view_settings(view)
                adopted += 1
        sublime.status_message("Notes: {} unsaved tabs are now files in {}".format(adopted, folder))


class ScratchSplitNoteCommand(sublime_plugin.TextCommand):
    """Move the selection, or everything from the cursor's line down, into a new note."""

    def run(self, edit):
        regions = [r for r in self.view.sel() if not r.empty()]
        if not regions:
            start = self.view.line(self.view.sel()[0].begin()).begin()
            regions = [sublime.Region(start, self.view.size())]
        text = "\n".join(self.view.substr(r) for r in regions).strip("\n") + "\n"
        if not text.strip():
            return
        # Write the new note before removing anything from this one.
        new_note(self.view.window(), text)
        for region in reversed(regions):
            self.view.erase(edit, region)


class ScratchSearchNotesCommand(sublime_plugin.WindowCommand):
    """Find notes containing every word typed; an empty search lists the most recent."""

    def run(self):
        self.window.show_input_panel("Search notes:", "", self.search, None, None)

    def search(self, query):
        words = query.lower().split()
        root = notes_dir()
        scores = activity_scores()
        hits = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if not name.lower().endswith(NOTE_EXTENSIONS):
                    continue
                path = os.path.join(folder, name)
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    continue
                haystack = (name + "\n" + text).lower()
                if not all(word in haystack for word in words):
                    continue
                # Show the first line that mentions the first word, and open there.
                line_no, snippet = 1, ""
                for i, line in enumerate(text.splitlines(), 1):
                    if line.strip() and (not words or words[0] in line.lower()):
                        line_no, snippet = i, line.strip()[:120]
                        break
                # Notes used recently or often come first; a match in the name counts triple.
                mtime = os.path.getmtime(path)
                rank = 0.2 + recency(mtime) + scores.get(path, 0)
                if words and all(word in name.lower() for word in words):
                    rank *= 3
                hits.append((rank, mtime, path, line_no, snippet))
        if not hits:
            sublime.status_message("No notes match '{}'".format(query))
            return
        hits.sort(reverse=True)
        hits = hits[: setting("max_results") or 200]
        items = [
            sublime.QuickPanelItem(os.path.relpath(path, root), snippet, ago(mtime))
            for _, mtime, path, _, snippet in hits
        ]

        def open_hit(index, flags=0):
            if index >= 0:
                _, _, path, line_no, _ = hits[index]
                self.window.open_file("{}:{}".format(path, line_no), sublime.ENCODED_POSITION | flags)

        self.window.show_quick_panel(
            items, open_hit, on_highlight=lambda i: open_hit(i, sublime.TRANSIENT)
        )


class ScratchNotesListener(sublime_plugin.EventListener):
    def on_load_async(self, view):
        apply_view_settings(view)

    def on_activated_async(self, view):
        if is_note(view) and os.path.isfile(view.file_name()):
            log_activity("open", os.path.realpath(view.file_name()))

    def on_post_save_async(self, view):
        if is_note(view):
            log_activity("edit", os.path.realpath(view.file_name()))

    def on_modified_async(self, view):
        if not is_note(view):
            return
        # Save once typing pauses, not on every key: kinder to whatever syncs the folder.
        count = view.change_count()
        delay = int(setting("save_delay_ms") or 1500)
        sublime.set_timeout_async(lambda: self.save(view, count), delay)

    def save(self, view, count):
        if view.is_valid() and view.change_count() == count and view.is_dirty() and is_note(view):
            os.makedirs(os.path.dirname(view.file_name()), exist_ok=True)
            view.run_command("save")

    def on_pre_close(self, view):
        if is_note(view) and view.is_dirty():
            view.run_command("save")

    def on_close(self, view):
        """Once closed, a note still called by its timestamp is renamed after its first line."""
        path = view.file_name()
        if not path or not STAMP_RE.match(os.path.basename(path)) or not os.path.isfile(path):
            return
        if os.path.realpath(os.path.dirname(path)) != os.path.realpath(inbox_dir()):
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if not text.strip():
                os.remove(path)  # nothing was ever written in it
                return
            title = slug(text)
            if not title:
                return
            stamp = os.path.basename(path)[:15]  # date and HHMM
            target = os.path.join(os.path.dirname(path), "{} {}.md".format(stamp, title))
            if not os.path.exists(target):
                os.rename(path, target)
                log_activity("rename", os.path.realpath(path), to=os.path.realpath(target))
        except OSError:
            pass
