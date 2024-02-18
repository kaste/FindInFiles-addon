## Sublime Text - Find in Files hacks

The plugin with the following features:

1. Make all lines in a find-in-files result buffer double-clickable.

2. Bind `<enter>` to do the same thing, namely go to that line.  (But also
set the column, well ... just the complete selection.)

3. Bind `,` and `.` to go to the previous or next match staying in the
result buffer. Just move the cursor ("navigate") around. Wraps at the edges but
stays in the same search. [1]

    But you can also bind `fif_addon_prev_match` and `fif_addon_next_match` on
    your own.

4. Bind `F5` to refresh the view, t.i. redo the _last_ search. Hm, :thinking:,
maybe we can change that and redo the search the cursor is currently in. But
for now it is the _last_ search in the buffer.

5. Bind `+` and `-` to change the context lines.  Assuming that you by default
show the result with some context lines, hitting `-` repeatedly will toggle
between no context and your default.

6. If you reuse the result buffer (and it is a tab, not the panel thing at the
bottom of the window), the tab moves with you so that closing the tab (aka
`ctrl+w`) brings you to the view where youy initiated the search.

7. Re-bind `ctrl+shift+f` to immediately do the search **if** you have exactly
one selection. Exclude untitled buffers in that case.  (You can turn this off
by setting `"leave_my_keys_alone.FindInFiles-addon": true` in the user
preferences.)

[1] You know, the result buffer can be re-used and then holds the results of
multiple searches.
