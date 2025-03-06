from __future__ import annotations
from collections import defaultdict
from contextlib import contextmanager
from functools import partial
from itertools import chain, tee
from pathlib import Path
import re

import sublime
import sublime_plugin

from typing import (
    Callable, DefaultDict, Dict, Iterable, Iterator, List, Literal,
    NamedTuple, Optional, Tuple, TypeVar, Union,
)
T = TypeVar("T")

filter_: Callable[[Iterable[Optional[T]]], Iterator[T]] = partial(filter, None)

SEARCH_INFO_RE = re.compile(r'(?:"(?P<pattern>.+)")(?: \((?P<flags>.+)\))?')
translate_flag = {
    "regex": "regex",
    "case sensitive": "case_sensitive",
    "whole word": "whole_word"
}


class fif_addon_quick_search(sublime_plugin.TextCommand):
    """Initiate Find in Files directly from the current selection

    Set `whole_word` depending on whether you have selected a word
    """
    def run(self, edit, where=None):
        view = self.view
        sel = view.sel()[0]

        window = view.window()
        assert window
        window.run_command("show_panel", {
            "panel": "find_in_files",
            "pattern": view.substr(sel),
            "where": where,
            "regex": False,
            "case_sensitive": False,
            # if you reverse-select a word that will not enable
            # "whole_word" as `view.word()`'s result is ordered.
            # Is that a bug or a feature?
            "whole_word": view.word(sel) == sel
        })
        window.run_command("find_all")
        window.run_command("focus_panel", {"name": "find_results"})


class fif_addon_refresh_last_search(sublime_plugin.TextCommand):
    """Delete last search result and do the search again

    This should look like a in-place refresh typically bound to `[F5]`.  The
    "toggle_*" arguments can be used to toggle these flags and immediately
    refresh the search result.  If `pause` is set, only the panel will open
    prefilled with the values from the previous search.
    """
    def run(
        self,
        edit,
        toggle_case_sensitive=False,
        toggle_regex=False,
        toggle_whole_word=False,
        pause=False
    ):
        view = self.view
        try:
            last_search_start = view.find_all(r"^Searching \d+ files")[-1]
        except IndexError:
            return

        search_headline_span = view.line(last_search_start.a)
        search_info = view.substr(search_headline_span)
        if (match := SEARCH_INFO_RE.search(search_info)):
            used_flags = {
                translate_flag[user_friendly_flag]
                for user_friendly_flag in flags.split(", ")
            } if (flags := match.group("flags")) else {}
            options = {
                "pattern": match.group("pattern"),
                **{
                    flag: (flag not in used_flags) if toggle else (flag in used_flags)
                    for flag, toggle in {
                        ("case_sensitive", toggle_case_sensitive),
                        ("regex", toggle_regex),
                        ("whole_word", toggle_whole_word)
                    }
                }
            }
            if toggle_regex:
                if options["regex"]:
                    options["pattern"] = re.escape(options["pattern"])  # type: ignore[type-var]
                else:
                    options["pattern"] = re.sub(r"\\(.)", r"\1", options["pattern"])  # type: ignore[arg-type]
        else:
            options = {}

        window = view.window()
        assert window  # we're a TextCommand on the UI thread!
        window.run_command("show_panel", {
            "panel": "find_in_files",
            **options
        })
        if pause:
            return

        previous_result = view.substr(sublime.Region(search_headline_span.b, view.size()))
        cursor = view.sel()[0].a
        offset = y_offset(view, cursor)
        row, col = view.rowcol(cursor)
        top_row, _ = view.rowcol(last_search_start.a)
        position = read_position(view)
        last_search_output_span = sublime.Region(
            max(0, last_search_start.a - 2),  # "-2" => also delete two preceding newlines
            view.size()
        )

        view.replace(edit, last_search_output_span, "")
        with modified_context_lines_setting(view):
            window.run_command("find_all")
        window.run_command("focus_panel", {"name": "find_results"})

        if last_search_output_span.a == 0 and is_result_buffer(view, window):
            on_search_finished(view, fix_leading_newlines)

        if row > top_row:
            restore_previous_cursor_ = partial(
                restore_previous_cursor,
                row_offset=offset,
                col=col,
                position_description=position
            )
            on_search_finished(view, restore_previous_cursor_)

        on_search_finished(view, partial(check_if_result_changed, previous_result=previous_result))


def y_offset(view, cursor):
    # type: (sublime.View, int) -> float
    _, cy = view.text_to_layout(cursor)
    _, vy = view.viewport_position()
    return cy - vy


def apply_offset(view: sublime.View, cursor: int, offset: float) -> None:
    _, cy = view.text_to_layout(cursor)
    vy = cy - offset
    vx, _ = view.viewport_position()
    view.set_viewport_position((vx, vy), animate=False)


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
        if r.a <= cursor:
            filename = view.substr(r)
            break

    line_candidates = []
    full_line = full_line_content_at(view, cursor)
    if full_line.strip():
        line_candidates.append(full_line)
        if (offset := column_offset_at(view, cursor)):
            line_candidates.append(full_line[offset:])

    for r in reversed(view.get_regions("match")):
        if r.a < last_search_start.a:
            break
        if r.a <= cursor:
            nearest_match = full_line_content_at(view, r.a)
            line_candidates.append(nearest_match)
            if (offset := column_offset_at(view, r.a)):
                line_candidates.append(nearest_match[offset:])
            break

    return (filename, list(filter_(line_candidates)))


def full_line_content_at(view: sublime.View, pt: int) -> str:
    return view.substr(view.full_line(pt))


class fif_addon_change_context_lines(sublime_plugin.TextCommand):
    def run(self, edit, more=False):
        view = self.view
        settings = sublime.load_settings("Preferences.sublime-settings")
        user_setting = settings.get("find_in_files_context_lines")
        if user_setting is None:
            window = view.window()
            assert window
            window.status_message(
                "error: no default for `find_in_files_context_lines` set in the preferences")
            print(
                "error: no default for `find_in_files_context_lines` set in the preferences\n"
                "That's a bit unfortunate as Sublime ships with a default.  "
                "Check if your user settings override that."
            )
            return

        if view.settings().has("fif_addon_current_context"):
            current = view.settings().get("fif_addon_current_context")
        else:
            current = user_setting

        if current == 0 and user_setting != 0:
            next_state = user_setting
        elif current == 0 or more:
            next_state = current + 2
        elif current == user_setting:
            next_state = 0
        else:
            next_state = max(0, current - 2)
        view.settings().set("fif_addon_current_context", next_state)

        view.run_command("fif_addon_refresh_last_search")


@contextmanager
def modified_context_lines_setting(view: sublime.View):
    settings = sublime.load_settings("Preferences.sublime-settings")
    user_setting = settings.get("find_in_files_context_lines")
    temporary_override = view.settings().get("fif_addon_current_context")
    if user_setting is None or temporary_override is None:
        yield

    else:
        settings.set("find_in_files_context_lines", temporary_override)
        try:
            yield
        finally:
            settings.set("find_in_files_context_lines", user_setting)


# 2024-12-14  Keep the old `EventListener` _registered_ for hot-reloading.
#             Remove when users likely have migrated.
class ContextLineInjector(sublime_plugin.EventListener):
    def on_text_command(self, view: sublime.View, command_name: str, args: Dict):
        ...
    def on_post_text_command(self, view: sublime.View, command_name: str, args: Dict):
        ...


def fix_leading_newlines(view):
    # We just modify the cursor as Sublime Text uses `append` for drawing
    set_sel(view, [sublime.Region(0)])
    view.run_command("right_delete")
    view.run_command("right_delete")


def check_if_result_changed(view, previous_result):
    window = view.window()
    if not window:
        return
    try:
        last_search_start = view.find_all(r"^Searching \d+ files")[-1]
    except IndexError:
        return

    search_headline_span = view.line(last_search_start.a)
    this_result = view.substr(sublime.Region(search_headline_span.b, view.size()))
    if this_result == previous_result:
        window.status_message("Search result already up-to-date.")


def restore_previous_cursor(view: sublime.View, row_offset, col, position_description):
    try:
        last_search_start = view.find_all(r"^Searching \d+ files")[-1]
    except IndexError:
        return

    start, end = last_search_start.a, view.size()
    filename, line_candidates = position_description
    if filename:
        try:
            start, end = next(
                (r.a, p.a)
                for p, r in pairwise(chain(
                    [sublime.Region(view.size())],
                    reversed(view.find_by_selector("entity.name.filename.find-in-files"))
                ))
                if start <= r.a < end
                if view.substr(r) == filename
            )
        except StopIteration:
            pass

    try:
        start = next(
            r.a
            for line in line_candidates
            for r in view.find_all(line, sublime.LITERAL)
            if start <= r.a < end
            if full_line_content_at(view, r.a).endswith(line)
        )
    except StopIteration:
        pass

    next_row, _ = view.rowcol(start)
    cursor_now = view.text_point(next_row, col)
    view.run_command("fif_addon_set_cursor", {"cursor": cursor_now, "offset": row_offset})


class fif_addon_set_cursor(sublime_plugin.TextCommand):
    def run(self, edit, cursor, offset):
        set_sel(self.view, [sublime.Region(cursor)])
        apply_offset(self.view, cursor, offset)


class fif_addon_replace_text(sublime_plugin.TextCommand):
    def run(self, edit, text, region: Tuple[int, int]):
        self.view.replace(edit, sublime.Region(*region), text)


def replace_view_content(view, text, region: Union[int, sublime.Region]) -> None:
    if isinstance(region, int):
        region_ = (region, region)
    else:
        region_ = (region.a, region.b)
    view.run_command("fif_addon_replace_text", {"text": text, "region": region_})


class fif_addon_listener(sublime_plugin.EventListener):
    previous_views: Dict[sublime.Window, sublime.View] = {}
    change_counts_by_window: Dict[sublime.Window, int] = {}
    handle_modified_events: Dict[sublime.Window, bool] = {}

    def on_activated_async(self, view):
        if is_applicable(view):
            this_package_name = Path(__file__).parent.stem
            syntax_file = f"Packages/{this_package_name}/FindInFiles.sublime-syntax"
            view.assign_syntax(syntax_file)

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
        if is_applicable(view):
            window = view.window()
            if self.handle_modified_events.get(window):
                current_cc = view.change_count()
                self.change_counts_by_window[window] = current_cc

    def on_pre_close(self, view):
        if is_applicable(view):
            window = view.window()
            self.change_counts_by_window.pop(window, None)
            self.previous_views.pop(window, None)
            self.handle_modified_events.pop(window, None)

    def on_deactivated(self, view):
        if view.element() is None:
            window = view.window()
            self.previous_views[window] = view

        if is_applicable(view):
            window = view.window()
            self.handle_modified_events[window] = False


def is_applicable(view):
    return view.match_selector(0, "text.find-in-files")


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
                    if preview_is_open(view):
                        view.run_command("fif_addon_goto", {"preview": True})
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
                    if preview_is_open(view):
                        view.run_command("fif_addon_goto", {"preview": True})
                    return


class fif_addon_goto(sublime_plugin.TextCommand):
    prev_loc = ("", -1)

    def run(self, edit, preview: bool | Literal["toggle"] = False):
        view = self.view
        window = view.window()
        assert window

        cursor = caret(view)
        r, _ = view.rowcol(cursor)
        prev_loc, self.prev_loc = self.prev_loc, (view.substr(view.line(cursor)), r)
        if (
            preview == "toggle"
            and preview_is_open(view)
            and prev_loc == self.prev_loc
        ):
            close_preview(view)
            return

        goto_positions = extract_goto_positions(view)
        # print("goto_positions", goto_positions)
        if not goto_positions:
            return

        selected = goto_positions[0]

        in_tab = sublime.ENCODED_POSITION
        side_by_side = (
            in_tab |
            sublime.FORCE_GROUP |
            sublime.SEMI_TRANSIENT |
            sublime.ADD_TO_SELECTION |
            sublime.CLEAR_TO_RIGHT
        )
        open_file = partial(window.open_file, selected.goto, group=-1)
        if not is_result_buffer(view, window):
            view_ = open_file(in_tab | sublime.TRANSIENT)
            window.focus_view(view)

        elif preview:
            view_ = open_file(side_by_side)
            window.focus_view(view)

        elif find_in_files_side_by_side_is_set():
            view_ = open_file(side_by_side)

        else:
            if preview_is_open(view):
                close_preview(view)
            view_ = open_file(in_tab)

        if view_:
            def carry_selection_to_view(view):
                sublime.set_timeout(lambda:
                    view.run_command("fif_addon_set_selection", {  # noqa: E128
                        "start": selected.start, "end": selected.end
                    })
                )

            when_loaded(view_, carry_selection_to_view)


class fif_addon_set_selection(sublime_plugin.TextCommand):
    def run(self, edit, start, end):
        view = self.view
        r = sublime.Region(view.text_point(*start), view.text_point(*end))
        set_sel(view, [r])
        view.show(r, True)


def close_preview(view: sublime.View):
    window = view.window()
    if not window:
        return

    group, _ = window.get_view_index(view)
    selected_sheets = window.selected_sheets_in_group(group)
    for other_sheet in selected_sheets:
        if (
            other_sheet != view.sheet()
            and other_sheet.is_semi_transient()
            and (other_view := other_sheet.view())
        ):
            other_view.close()
    window.run_command("unselect_others")


def find_in_files_side_by_side_is_set() -> bool:
    settings = sublime.load_settings("Preferences.sublime-settings")
    return settings.get("find_in_files_side_by_side")


def preview_is_open(view: sublime.View) -> bool:
    window = view.window()
    if not window:
        return False
    group, _ = window.get_view_index(view)
    selected_sheets = window.selected_sheets_in_group(group)
    return len(selected_sheets) == 2 and view.sheet() in selected_sheets


def is_result_buffer(view: sublime.View, window: sublime.Window) -> bool:
    return view in window.views()


SEARCH_SUMMARY_RE = re.compile(r"\d+ match(es)? .*")
SEARCH_HEADER_RE = re.compile(r"^Searching \d+ files .*")
LoadedCallback = Callable[[sublime.View], None]
_on_loaded: DefaultDict[sublime.View, List[LoadedCallback]] = defaultdict(list)
_on_search_finished: DefaultDict[sublime.View, List[LoadedCallback]] = defaultdict(list)
_pending_first_result: set[sublime.View] = set()


def on_search_finished(view: sublime.View, fn: LoadedCallback) -> None:
    _on_search_finished[view].append(fn)


class fif_addon_wait_for_search_to_be_done_listener(sublime_plugin.EventListener):
    def on_modified(self, view):
        if is_applicable(view):
            caret = view.sel()[0].a
            if view.size() - caret in (
                0,  # on new buffers
                1   # when reusing views because of a trailing \n
            ):
                _pending_first_result.add(view)

            elif (
                view in _pending_first_result
                and (text := view.substr(view.line(caret)))
                and SEARCH_HEADER_RE.match(text)
                and any(r.a > caret for r in view.get_regions("match"))
            ):
                fx = partial(view.run_command, "fif_addon_next_match")
                if caret == 0:
                    sublime.set_timeout(fx)
                else:
                    fx()
                _pending_first_result.discard(view)

            text = view.substr(view.line(view.size() - 1))
            if SEARCH_SUMMARY_RE.search(text) is None:
                return

            update_searching_headline(view, text)
            run_handlers(view, _on_search_finished)
            _pending_first_result.discard(view)


def update_searching_headline(view, text):
    if text.startswith("0"):
        return

    last_search_start = view.find(
        r"^Searching \d+ files .*",
        view.size(),
        sublime.FindFlags.REVERSE
    )
    if view.substr(last_search_start).endswith(text):
        return

    replace_view_content(view, f", {text}", last_search_start.b)


def when_loaded(view: sublime.View, kont: LoadedCallback) -> None:
    if view.is_loading():
        _on_loaded[view].append(kont)
    else:
        kont(view)


class fif_addon_await_loading_views(sublime_plugin.EventListener):
    def on_load(self, view):
        run_handlers(view, _on_loaded)


def run_handlers(view, storage: Dict[sublime.View, List[LoadedCallback]]):
    try:
        fns = storage.pop(view)
    except KeyError:
        return

    for fn in fns:
        sublime.set_timeout(partial(fn, view))


def caret(view: sublime.View) -> int:
    return view.sel()[0].b


def column_offset_at(view: sublime.View, pt: int) -> int:
    line_region = view.line(pt)
    for r, scope in view.extract_tokens_with_scopes(line_region):
        if "constant.numeric.line-number." in scope:
            return r.b + 2 - line_region.a  # 2 spaces or `: `
    else:
        return 0


class GotoDefinition(NamedTuple):
    filename: str
    start: tuple[int, int]
    end: tuple[int, int]

    @property
    def goto(self):
        return f"{self.filename}:{self.start[0]}:{self.start[1]}"


def extract_goto_positions(view) -> list[GotoDefinition]:
    """
    Extract goto positions from search buffer based on user selections.
    Supports multiple cursors, and selections across multiple matches.
    """
    frozen_sel = list(view.sel())
    matches = view.get_regions("match")
    filenames = view.find_by_selector("entity.name.filename.find-in-files")

    results = []
    for region in frozen_sel:
        if _is_selection_within_code_block(view, region):
            results += _extract_position_from_region(view, region, filenames)

        elif (file_region := _is_selection_within_filename(region, filenames)):
            results += _handle_filename_selection(view, region, file_region, matches)

        else:
            results += _handle_free_form_selection(view, region, filenames, matches)

    return results


def _is_selection_within_code_block(view: sublime.View, region: sublime.Region) -> bool:
    """Determine if a selection is completely within a single code block."""
    if not _is_in_code_block(view, region.begin()):
        return False
    if len(view.lines(region)) == 1:  # optimize for the typical call
        return True
    return _get_code_block_bounds(view, region.begin()).contains(region)


def _is_in_code_block(view: sublime.View, pt: int) -> bool:
    """Determine if a point is within a code block (lines that start with space)."""
    line_region = view.line(pt)
    line_text = view.substr(line_region)
    return line_text.startswith(' ')


def _is_selection_within_filename(
    region: sublime.Region,
    filenames: list[sublime.Region]
) -> sublime.Region | Literal[False]:
    for file_region in filenames:
        if all(file_region.a <= pt <= file_region.b for pt in region):
            return file_region
    return False


def _get_code_block_bounds(view: sublime.View, pt: int) -> sublime.Region:
    """Get the boundaries of the code block containing the given point."""
    separator = r"^\S.*\n|^\s+\.\..*\n|^\n"
    start     = view.find(separator, pt, sublime.FindFlags.REVERSE)  # noqa: E221
    end       = view.find(separator, pt)                             # noqa: E221
    start_pt  = start.b if start else pt                             # noqa: E221
    end_pt    = end.a if end else pt                                 # noqa: E221
    return sublime.Region(start_pt, end_pt)


def _find_containing_file(
    view: sublime.View,
    pt: int,
    filenames: list[sublime.Region]
) -> str | None:
    """Find the filename for the code block containing the given point."""
    for file_region in reversed(filenames):
        if file_region.a <= pt:
            return view.substr(file_region)
    return None


def _extract_position_from_region(
    view: sublime.View,
    region: sublime.Region,
    filename: str | list[sublime.Region]
) -> list[GotoDefinition]:
    """Extract position information from a region."""
    if isinstance(filename, list):
        filename = _find_containing_file(view, region.a, filename)  # type: ignore[assignment]
        if not filename:
            return []
        assert not isinstance(filename, list)

    col_offset = column_offset_at(view, region.a)

    # do not work with begin() and end() to preserve the direction
    # of the selection
    start_line  = view.line(region.a)                                # noqa: E221
    start_line_ = view.substr(start_line)
    start_row   = int(start_line_[:col_offset].strip(" :"))          # noqa: E221
    start_col   = max(0, region.a - start_line.a - col_offset)       # noqa: E221

    if region.empty():
        end_row  = start_row                                         # noqa: E221
        end_line = start_line
    else:
        end_line    = view.line(region.b)                            # noqa: E221
        end_line_   = view.substr(end_line)                          # noqa: E221
        end_row     = int(end_line_[:col_offset].strip(" :"))        # noqa: E221
    end_col     = max(0, region.b - end_line.a - col_offset)         # noqa: E221

    return [GotoDefinition(filename, (start_row - 1, start_col), (end_row - 1, end_col))]


def _handle_filename_selection(
    view: sublime.View,
    region: sublime.Region,
    file_region: sublime.Region,
    matches: list[sublime.Region]
) -> list[GotoDefinition]:
    """Handle a cursor position on a filename."""
    for m in matches:
        if m.a > file_region.a:
            filename = view.substr(file_region)
            return _extract_position_from_region(view, m, filename)
    return []


def _handle_free_form_selection(
    view: sublime.View,
    region: sublime.Region,
    filenames: list[sublime.Region],
    matches: list[sublime.Region]
) -> Iterable[GotoDefinition]:
    """Handle a free-form selection that spans multiple code blocks or files."""
    # Expand partially selected code blocks
    start = (
        _get_code_block_bounds(view, region.begin())
        if _is_in_code_block(view, region.begin())
        else region
    )
    end = (
        _get_code_block_bounds(view, region.end())
        if _is_in_code_block(view, region.end())
        else region
    )
    selection = sublime.Region(start.begin(), end.end())

    return chain.from_iterable(
        _extract_position_from_region(view, m, filenames)
        for m in matches
        if selection.a <= m.a <= selection.b
    )


# # UTILS


def set_sel(view: sublime.View, selection: List[sublime.Region]) -> None:
    sel = view.sel()
    sel.clear()
    sel.add_all(selection)


def pairwise(iterable: Iterable[T]) -> Iterable[tuple[T, T]]:
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)
