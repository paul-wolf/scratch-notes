# scratch-notes

Sublime Text as a note editor that shares a folder with Obsidian (`~/notes`).

## ScratchNotes (Sublime plugin)

| Key | What it does |
|---|---|
| ⌘N | New note: a tab that is already a file in `~/notes/inbox`, saved shortly after you stop typing; renamed after its first line when closed |
| ⌃⌥F | Search all notes; every word must match; recently and often used notes first; empty search lists the most recent |
| ⌃⌥S | Move the selection, or everything from the cursor's line down, into a new note |
| ⌥⌘N | Plain untitled tab (what ⌘N used to do) |

Command palette, under "Notes:": also **Adopt Unsaved Tabs as Files**, which turns every
unsaved tab into a file in `~/notes/sublime`, and **Settings**.

Any file under `~/notes` opened in Sublime autosaves and gets Obsidian-like wrapping.
Opens and edits are logged to `~/Library/Application Support/ScratchNotes/activity.jsonl`
for search ranking.

Install: link the package into Sublime.

```
ln -s ~/prj/scratch-notes/ScratchNotes ~/Library/Application\ Support/Sublime\ Text/Packages/ScratchNotes
```

Settings (folder, inbox, save delay, wrap width) are in `ScratchNotes/ScratchNotes.sublime-settings`.

## sublime_export.py

Copies unsaved tabs out of Sublime's session file into `~/notes/sublime`, one file per tab,
without touching Sublime. Safe to re-run. `--dry-run` shows what it would do.
