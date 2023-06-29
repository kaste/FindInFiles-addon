from collections import defaultdict
from contextlib import contextmanager
from functools import partial
import re

import sublime
import sublime_plugin

from typing import Callable, DefaultDict, Dict, List


class fif_addon_refresh_last_search(sublime_plugin.TextCommand):
    """Delete last search result and do the search again

    This should look like a in-place refresh typically bound to `[F5]`
    """
    def run(self, edit):
        view = self.view
        try:
            last_search_start = view.find_all(r"^Searching \d+ files")[-1]
        except IndexError:
            return

        cursor = view.sel()[0].a
        row, col = view.rowcol(cursor)
        top_row, _ = view.rowcol(last_search_start.a)

        last_search_output_span = sublime.Region(
            max(0, last_search_start.a - 2),  # "-2" => also delete two preceding newlines
            view.size()
        )
        view.replace(edit, last_search_output_span, "")

        window = view.window()
        assert window  # we're a TextCommand on the UI thread!
        window.run_command("chain", {
            "commands": [
                ["show_panel", {"panel": "find_in_files"}],
                ["find_all"],
            ]
        })

        def await_first_draw(cc, sink):
            if view.change_count() == cc:
                sublime.set_timeout(partial(await_first_draw, view.change_count(), sink), 1)
            else:
                sink()

        def fix_leading_newlines():
            # We just modify the cursor as Sublime Text uses `append` for drawing
            set_sel(view, [sublime.Region(0)])
            view.run_command("right_delete")
            view.run_command("right_delete")

        if last_search_output_span.a == 0:
            fix_task = partial(await_first_draw, view.change_count(), fix_leading_newlines)
            sublime.set_timeout(fix_task)

        def await_draw(cc, sink):
            # wait for the view to stabilize!
            if view.change_count() == cc:
                sink()
            else:
                sublime.set_timeout(partial(await_draw, view.change_count(), sink), 50)

        def after_search_finished():
            offset = row - top_row
            try:
                last_search_start = view.find_all(r"^Searching \d+ files")[-1]
            except IndexError:
                return
            top_row_now, _ = view.rowcol(last_search_start.a)
            next_row = top_row_now + offset
            cursor_now = view.text_point(next_row, col)
            view.run_command("fif_addon_set_cursor", {"cursor": cursor_now})

        if row > top_row:
            wait = partial(await_draw, view.change_count(), after_search_finished)
            sublime.set_timeout(wait, 10)


class fif_addon_set_cursor(sublime_plugin.TextCommand):
    def run(self, edit, cursor):
        set_sel(self.view, [sublime.Region(cursor)])
        self.view.show(cursor)


regex = re.compile(r"\d+ match(es)? .*")


class fif_addon_wait_for_search_to_be_done_listener(sublime_plugin.EventListener):
    def is_applicable(self, view):
        syntax = view.settings().get("syntax")
        return syntax.endswith("Find Results.hidden-tmLanguage") if syntax else False

    def on_modified(self, view):
        if self.is_applicable(view):
            text = view.substr(view.line(view.size() - 1))
            if text.startswith("0"):
                return

            if regex.search(text) is None:
                return

            last_search_start = view.find(
                r"^Searching \d+ files .*",
                view.size(),
                sublime.FindFlags.REVERSE  # type: ignore[attr-defined]
            )
            if view.substr(last_search_start).endswith(text):
                return

            with restore_selection(view):
                set_sel(view, [sublime.Region(last_search_start.b)])
                view.run_command("insert", {"characters": f", {text}"})


class fif_addon_listener(sublime_plugin.EventListener):
    previous_views: Dict[sublime.Window, sublime.View] = {}
    change_counts_by_window: Dict[sublime.Window, int] = {}
    handle_modified_events: Dict[sublime.Window, bool] = {}

    def is_applicable(self, view):
        syntax = view.settings().get("syntax")
        return syntax.endswith("Find Results.hidden-tmLanguage") if syntax else False

    def on_activated_async(self, view):
        if self.is_applicable(view):
            view.settings().set("result_line_regex", "^ +([0-9]+)")

            current_cc = view.change_count()
            window = view.window()
            self.handle_modified_events[window] = True
            previous_cc = self.change_counts_by_window.get(window)
            if previous_cc != current_cc:
                self.change_counts_by_window[window] = current_cc
                previous_view = self.previous_views.get(window)
                if previous_view:
                    place_view(window, view, previous_view)

    def on_modified_async(self, view):
        if self.is_applicable(view):
            window = view.window()
            if self.handle_modified_events.get(window):
                current_cc = view.change_count()
                self.change_counts_by_window[window] = current_cc

    def on_pre_close(self, view):
        if self.is_applicable(view):
            window = view.window()
            self.change_counts_by_window.pop(window, None)
            self.previous_views.pop(window, None)
            self.handle_modified_events.pop(window, None)

    def on_deactivated(self, view):
        if view.element() is None:
            window = view.window()
            self.previous_views[window] = view

        if self.is_applicable(view):
            window = view.window()
            self.handle_modified_events[window] = False


def place_view(window: sublime.Window, view: sublime.View, after: sublime.View) -> None:
    view_group, current_index = window.get_view_index(view)
    group, index = window.get_view_index(after)
    if view_group == group:
        wanted_index = index + 1 if index < current_index else index
        window.set_view_index(view, group, wanted_index)


class fif_addon_next_match(sublime_plugin.TextCommand):
    def run(self, edit):
        def carets(view):
            yield view.sel()[0].b
            try:
                yield view.find_all(r"^Searching \d+ files")[-1].a
            except IndexError:
                return

        view = self.view
        regions = view.get_regions("match")
        for caret in carets(view):
            for r in regions:
                if r.begin() > caret:
                    set_sel(view, [r])
                    view.show(r, True)
                    return


class fif_addon_prev_match(sublime_plugin.TextCommand):
    def run(self, edit):
        def carets(view):
            yield view.sel()[0].b
            yield view.size()

        view = self.view
        regions = view.get_regions("match")
        for caret in carets(view):
            for r in reversed(regions):
                if r.end() < caret:
                    set_sel(view, [r])
                    view.show(r, True)
                    return


class fif_addon_goto(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        window = view.window()
        assert window

        r, c = view.rowcol(caret(view))
        column_offset = _column_offset(view)
        col = max(0, c - column_offset)
        s = view.sel()[0]
        count_line_breaks = len(view.lines(s)) - 1
        len_s = s.b - s.a
        if len_s < 0:
            len_s += count_line_breaks * column_offset
        else:
            len_s -= count_line_breaks * column_offset

        with restore_selection(view):
            view.run_command("move_to", {"to": "hardbol"})
            window.run_command("next_result")

            view_ = window.active_view()

            def carry_selection_to_view(view):
                caret_ = caret(view) + col
                set_sel(view, [sublime.Region(caret_ - len_s, caret_)])

            if view_:
                when_loaded(view_, carry_selection_to_view)


Callback = Callable[[sublime.View], None]
VIEWS_YET_TO_BE_LOADED: DefaultDict[sublime.View, List[Callback]] \
    = defaultdict(list)


def when_loaded(view: sublime.View, kont: Callback) -> None:
    if view.is_loading():
        VIEWS_YET_TO_BE_LOADED[view].append(kont)
    else:
        kont(view)


class fif_addon_await_loading_views(sublime_plugin.EventListener):
    def on_load(self, view):
        try:
            fns = VIEWS_YET_TO_BE_LOADED.pop(view)
        except KeyError:
            return

        for fn in fns:
            sublime.set_timeout(lambda: fn(view))


@contextmanager
def restore_selection(view: sublime.View):
    frozen_sel = [s for s in view.sel()]
    yield
    set_sel(view, frozen_sel)


def caret(view: sublime.View) -> int:
    return view.sel()[0].b


def _column_offset(view: sublime.View) -> int:
    line_region = view.line(caret(view))
    for r, scope in view.extract_tokens_with_scopes(line_region):
        if "constant.numeric.line-number." in scope:
            return r.b + 2 - line_region.a  # 2 spaces or `: `
    else:
        return 0


def set_sel(view: sublime.View, selection: List[sublime.Region]) -> None:
    sel = view.sel()
    sel.clear()
    sel.add_all(selection)
