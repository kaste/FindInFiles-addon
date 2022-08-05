import sublime
import sublime_plugin


class fif_addon_remove_last_search(sublime_plugin.TextCommand):
    def is_enabled(self):
        return self.view.match_selector(0, "text.find-in-files")

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
