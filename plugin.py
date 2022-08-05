import sublime
import sublime_plugin


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
