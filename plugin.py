from contextlib import contextmanager
from functools import partial

import sublime
import sublime_plugin

from typing import Dict, List


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


class fif_addon_listener(sublime_plugin.EventListener):
    previous_views: Dict[sublime.Window, sublime.View] = {}
    change_counts_by_window: Dict[sublime.Window, int] = {}

    def is_applicable(self, view):
        syntax = view.settings().get("syntax")
        return syntax.endswith("Find Results.hidden-tmLanguage") if syntax else False

    def on_activated_async(self, view):
        if self.is_applicable(view):
            view.settings().set("result_line_regex", "^ +([0-9]+)")

            current_cc = view.change_count()
            window = view.window()
            previous_cc = self.change_counts_by_window.get(window)
            if previous_cc != current_cc:
                self.change_counts_by_window[window] = current_cc
                previous_view = self.previous_views.get(window)
                if previous_view and previous_cc is not None:
                    place_view(window, view, previous_view)

    def on_pre_close(self, view):
        if self.is_applicable(view):
            window = view.window()
            self.change_counts_by_window.pop(window, None)
            self.previous_views.pop(window, None)

    def on_deactivated(self, view):
        if view.element() is None:
            window = view.window()
            self.previous_views[window] = view


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
        window = view.window(); assert window

        r, c = view.rowcol(caret(view))
        column_offset = _column_offset(view)
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
            caret_ = caret(view_) + c - column_offset
            set_sel(view_, [sublime.Region(caret_ - len_s, caret_)])


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
