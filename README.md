## Find in Files add-on for Sublime Text

This plugin enhances the Find in Files feature of Sublime Text.  It attaches to
the result buffer automatically and adds the following features:

1. Make all lines in a find-in-files result buffer double-clickable.  Bind
`<enter>` to do the same thing, namely go to that line.  (But also set the column,
well ... just set the complete selection.)

2. Also, register the filenames as local symbols for quick navigation and outlines.
Use `ctrl|super+r` (Sublime's default) to open the symbols panel, or however you
use that in your daily routine.  (E.g. I have a global shortcut to jump from
symbol to symbol.)

3. Bind `,` and `.` to go to the previous or next match staying in the
result buffer. Just move the cursor ("navigate") around.

    But you can also bind `fif_addon_prev_match` and `fif_addon_next_match` on
    your own.

4. Bind `ctrl+enter` to open a preview, side-by-side.  The preview will update
when you navigate around.  Both, `enter` and `ctrl+enter` will close the preview.
As there is no side-by-side to a results _panel_, this will only work for result
buffers.  Also, if you already use the newish "find_in_files_side_by_side" setting,
there is no real difference as you already opted-in to always use a side-by-side
view.  (Hint: Turn `find_in_files_side_by_side` off and use the preview feature
here.)

5. Bind `+` and `-` to change the number of context lines.  For ease of use,
hit `-` repeatedly as a toggle between no context and your default, or if your
default _is_ no context between that and some context.

6. Bind `f5` to refresh the view, t.i. redo the _last_ search. Hm, 🤔, maybe we
can change that and redo the search the cursor is currently in. But for now it is
the _last_ search in the buffer.

7. Bind `alt+c`[3] to toggle case sensitivity, `alt-w` to toggle the whole word
flag and redo the search immediately.

8. Bind `alt+r` to toggle regex mode.  The pattern will be escaped/unescaped
and the panel will open to edit the pattern further.

9. If you reuse the result buffer (and it is a tab, not the panel thing at the
bottom of the window), the tab moves with you so that closing the tab (aka
`ctrl+w`) brings you to the view where you initiated the search.

10. Add the search summary (e.g. "2 matches across 2 files") to the search
header line ("Searching 9 files for ...")

11. Re-bind `ctrl+shift+f` to immediately do the search **if** you have exactly
one selection. Exclude untitled buffers in that case.  (You can turn this off
by setting `"leave_my_keys_alone.FindInFiles-addon": true` in the user
preferences.)  Sets "whole_word" if you've selected a whole word, unsets it
if that's not the case.  Also normalizes `case_sensitive` and `regex` to
`false`.

[1] On Mac, the standard `super+alt` modifier is used.  Generally, these should
be just the standard bindings, you already use in the Find-panel to toggle the
switches.


### 1

Registering "local symbols" populates the Goto panel.  I use it in combination
with the [InlineOutline](https://packagecontrol.io/packages/InlineOutline) plugin,
which looks like so:

![Outline View using InlineOutline](<docs/Outline View.jpg>)


### 2

I personally like it when `escape` closes the results view.  You can add that
to your own key bindings.  E.g.

```
    {
        "keys": ["escape"],
        "command": "close",
        "context": [
            { "key": "selector", "operand": "text.find-in-files" },
            // negate all default escape contexts, even if they're not likely to ever match
            { "key": "auto_complete_visible", "operator": "not_equal" },
            { "key": "has_prev_field", "operator": "not_equal" },
            { "key": "has_next_field", "operator": "not_equal" },
            { "key": "num_selections", "operator": "equal", "operand": 1 },
            { "key": "overlay_visible", "operator": "not_equal" },
            { "key": "panel_visible", "operator": "not_equal" },
            { "key": "popup_visible", "operator": "not_equal" },
        ]
    }
```
