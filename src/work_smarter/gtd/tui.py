"""Small dependency-free, vim-like GTD terminal UI."""

from __future__ import annotations

import curses
from pathlib import Path

from work_smarter.composition import open_workspace
from work_smarter.gtd.models import ClarifyDecision
from work_smarter.gtd.service import GtdService


class GtdTui:
    def __init__(self, screen: curses.window, workspace: Path) -> None:
        self.screen = screen
        self.service = GtdService(open_workspace(workspace))
        self.mode = "inbox"
        self.index = 0
        self.message = "j/k: move  Tab: inbox/tasks  c: capture  n: next action  s: start  q: quit"

    def _items(self):
        return self.service.list_inbox() if self.mode == "inbox" else self.service.list_tasks()

    def draw(self) -> None:
        self.screen.erase()
        items = self._items()
        self.index = min(self.index, max(0, len(items) - 1))
        self.screen.addstr(
            0, 0, f"WORK SMARTER  [{self.mode.upper()}]  {len(items)} items", curses.A_BOLD
        )
        self.screen.addstr(1, 0, "─" * 78)
        for row, item in enumerate(items[: self.screen.getmaxyx()[0] - 5], 2):
            title = str(getattr(item, "title", getattr(item, "text", "")))[:68]
            marker = ">" if row - 2 == self.index else " "
            self.screen.addstr(row, 0, f"{marker} {getattr(item, 'id', ''):<14} {title}")
        self.screen.addstr(
            self.screen.getmaxyx()[0] - 2, 0, self.message[: self.screen.getmaxyx()[1] - 1]
        )
        self.screen.refresh()

    def prompt(self, label: str) -> str:
        self.screen.addstr(self.screen.getmaxyx()[0] - 1, 0, label)
        self.screen.clrtoeol()
        curses.echo()
        value = self.screen.getstr().decode(errors="replace").strip()
        curses.noecho()
        return value

    def run(self) -> None:
        curses.curs_set(0)
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                self.index += 1
            elif key in (curses.KEY_UP, ord("k")):
                self.index = max(0, self.index - 1)
            elif key in (9, ord("l")):
                self.mode = "tasks" if self.mode == "inbox" else "inbox"
                self.index = 0
            elif key == ord("c"):
                text = self.prompt("capture: ")
                if text:
                    self.service.capture(text, source="tui")
                    self.message = "Captured to Inbox"
            elif key == ord("n") and self.mode == "inbox" and self._items():
                item = self._items()[self.index]
                self.service.clarify(item.id, ClarifyDecision.NEXT)
                self.message = "Moved to Next Action"
            elif key == ord("s") and self.mode == "tasks" and self._items():
                self.service.start_task(self._items()[self.index].id)
                self.message = "Started task (WIP=1)"


def run_tui(workspace: Path) -> None:
    curses.wrapper(lambda screen: GtdTui(screen, workspace).run())


__all__ = ["run_tui"]
