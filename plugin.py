from collections import defaultdict
from contextlib import contextmanager
from functools import partial
import re

import sublime
import sublime_plugin

from typing import Callable, DefaultDict, Dict, List, Optional, Tuple, Union
Callback = Callable[[sublime.View], None]


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
        row_offset = row - top_row
        position = read_position(view)

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

        if last_search_output_span.a == 0:
            on_next_modification(view, fix_leading_newlines)

        if row > top_row:
            restore_previous_cursor_ = partial(
                restore_previous_cursor,
                row_offset=row_offset,
                col=col,
                position_description=position
            )
            on_search_finished(view, restore_previous_cursor_)


def read_position(view: sublime.View):
    cursor = view.sel()[0].a
    try:
        last_search_start = view.find_all(r"^Searching \d+ files")[-1]
    except IndexError:
        last_search_start = sublime.Region(0)

    filename = None
    for r in reversed(view.find_by_selector("entity.name.filename.find-in-files")):
        if r.a < last_search_start.a:
            break
        if r.a < cursor:
            filename = line_content_on(view, r.a)
            break

    nearest_match = None
    for r in reversed(view.get_regions("match")):
        if r.a < cursor:
            nearest_match = line_content_on(view, r.a)
            break

    return (filename, line_content_on(view, cursor), nearest_match)


def line_content_on(view: sublime.View, pt: int) -> str:
    return view.substr(view.line(pt))


class fif_addon_change_context_lines(sublime_plugin.TextCommand):
    def run(self, edit, more=False):
        self.view.run_command("fif_addon_refresh_last_search")


class ContextLineInjector(sublime_plugin.EventListener):
    user_setting: Optional[int] = None

    def on_text_command(self, view: sublime.View, command_name: str, args: Dict):
        if command_name == "fif_addon_change_context_lines":
            settings = sublime.load_settings("Preferences.sublime-settings")
            if self.user_setting is None:
                self.user_setting = settings.get("find_in_files_context_lines")
                if self.user_setting is None:
                    return

            if view.settings().has("fif_addon_current_context"):
                current = view.settings().get("fif_addon_current_context")
            else:
                current = self.user_setting

            if current == 0:
                next_state = self.user_setting
            elif args.get("more"):
                next_state = current + 2
            elif current == self.user_setting:
                next_state = 0
            else:
                next_state = max(0, current - 2)
            view.settings().set("fif_addon_current_context", next_state)
            settings.set("find_in_files_context_lines", next_state)

    def on_post_text_command(self, view: sublime.View, command_name: str, args: Dict):
        if command_name == "fif_addon_change_context_lines":
            settings = sublime.load_settings("Preferences.sublime-settings")
            if self.user_setting is not None:
                settings.set("find_in_files_context_lines", self.user_setting)


def fix_leading_newlines(view):
    # We just modify the cursor as Sublime Text uses `append` for drawing
    set_sel(view, [sublime.Region(0)])
    view.run_command("right_delete")
    view.run_command("right_delete")


def restore_previous_cursor(view, row_offset, col, position_description=None):
    try:
        last_search_start = view.find_all(r"^Searching \d+ files")[-1]
    except IndexError:
        return

    if position_description:
        best_line = last_search_start

        filename, exact_line_content, nearest_match_line_content = position_description
        if filename:
            try:
                best_line = next(
                    r
                    for r in reversed(view.find_by_selector("entity.name.filename.find-in-files"))
                    if r.a > best_line.a
                    if line_content_on(view, r.a) == filename
                )
            except StopIteration:
                pass

        try:
            best_line = next(
                r
                for line in (exact_line_content, nearest_match_line_content)
                if line
                for r in view.find_all(line, sublime.LITERAL)
                if r.a > best_line.a
                if line_content_on(view, r.a) == line
            )
        except StopIteration:
            pass

        next_row, _ = view.rowcol(best_line.a)

    else:
        top_row_now, _ = view.rowcol(last_search_start.a)
        next_row = top_row_now + row_offset
    cursor_now = view.text_point(next_row, col)
    view.run_command("fif_addon_set_cursor", {"cursor": cursor_now})


class fif_addon_set_cursor(sublime_plugin.TextCommand):
    def run(self, edit, cursor):
        set_sel(self.view, [sublime.Region(cursor)])
        self.view.show(cursor)


class fif_addon_replace_text(sublime_plugin.TextCommand):
    def run(self, edit, text, region: Tuple[int, int]):
        self.view.replace(edit, sublime.Region(*region), text)


def replace_view_content(view, text, region: Union[int, sublime.Region]) -> None:
    if isinstance(region, int):
        region_ = (region, region)
    else:
        region_ = (region.a, region.b)
    view.run_command("fif_addon_replace_text", {"text": text, "region": region_})


_on_search_finished: DefaultDict[sublime.View, List[Callback]] = defaultdict(list)
_on_next_modification: DefaultDict[sublime.View, List[Callback]] = defaultdict(list)


def on_search_finished(view: sublime.View, fn: Callback) -> None:
    _on_search_finished[view].append(fn)


def on_next_modification(view: sublime.View, fn: Callback) -> None:
    _on_next_modification[view].append(fn)


regex = re.compile(r"\d+ match(es)? .*")


class fif_addon_wait_for_search_to_be_done_listener(sublime_plugin.EventListener):
    def is_applicable(self, view):
        syntax = view.settings().get("syntax")
        return syntax.endswith("Find Results.hidden-tmLanguage") if syntax else False

    def on_modified(self, view):
        if self.is_applicable(view):
            run_handlers(view, _on_next_modification)

            text = view.substr(view.line(view.size() - 1))
            if regex.search(text) is None:
                return

            update_searching_headline(view, text)
            run_handlers(view, _on_search_finished)


def update_searching_headline(view, text):
    if text.startswith("0"):
        return

    last_search_start = view.find(
        r"^Searching \d+ files .*",
        view.size(),
        sublime.FindFlags.REVERSE  # type: ignore[attr-defined]
    )
    if view.substr(last_search_start).endswith(text):
        return

    replace_view_content(view, f", {text}", last_search_start.b)


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
    if current_index == -1:
        return
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


VIEWS_YET_TO_BE_LOADED: DefaultDict[sublime.View, List[Callback]] \
    = defaultdict(list)


def when_loaded(view: sublime.View, kont: Callback) -> None:
    if view.is_loading():
        VIEWS_YET_TO_BE_LOADED[view].append(kont)
    else:
        kont(view)


class fif_addon_await_loading_views(sublime_plugin.EventListener):
    def on_load(self, view):
        run_handlers(view, VIEWS_YET_TO_BE_LOADED)


def run_handlers(view, storage: Dict[sublime.View, List[Callback]]):
    try:
        fns = storage.pop(view)
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
