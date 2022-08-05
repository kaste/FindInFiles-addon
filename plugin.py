import sublime
import sublime_plugin

from typing import List


class fif_addon_refresh_last_search(sublime_plugin.TextCommand):
    """Delete last search result and do the search again

    This should look like a in-place refresh typically bound to `[F5]`
    """
    def run(self, edit):
        view = self.view
        try:
            last_search_start = view.find_all(r"^Searching \d files")[-1]
        except IndexError:
            return

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


class fif_addon_listener(sublime_plugin.EventListener):
    def is_applicable(self, view):
        syntax = view.settings().get("syntax")
        return syntax.endswith("Find Results.hidden-tmLanguage") if syntax else False

    def on_activated_async(self, view):
        if self.is_applicable(view):
            view.settings().set("result_line_regex", "^ +([0-9]+)")


class fif_addon_next_match(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        caret = view.sel()[0].b

        for r in view.get_regions("match"):
            if r.begin() > caret:
                set_sel(view, [r])
                view.show(r, False)
                break


class fif_addon_prev_match(sublime_plugin.TextCommand):
    def run(self, edit):
        view = self.view
        caret = view.sel()[0].b

        for r in reversed(view.get_regions("match")):
            if r.end() < caret:
                set_sel(view, [r])
                view.show(r, False)
                break


def set_sel(view: sublime.View, selection: List[sublime.Region]) -> None:
    sel = view.sel()
    sel.clear()
    sel.add_all(selection)
