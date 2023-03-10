## Sublime Text - Find in Files hacks

The plugin with the following features:

1. Make all lines in a find-in-files result buffer double-clickable.

2. Bind `<enter>` to do the same thing, namely go to that line.  (But also
set the column, well ... just the complete selection.)

3. Bind `ctrl+,` and `ctrl+.` to go to the previous or next match staying in the
result buffer. Just move the cursor ("navigate") around. Wraps at the edges but
stays in the same search. [1]

4. Bind `F5` to refresh the view, t.i. redo the _last_ search. Hm, :thinking:,
maybe we can change that and redo the search the cursor is currently in. But
for now it is the _last_ search in the buffer.

5. If you reuse the result buffer (and it is a tab, not the panel thing at the
bottom of the window), the tab moves with you so that `ctrl+w` (aka closing the
tab) brings you to the view where youy initiated the search.

6. Re-bind `ctrl+shift+f` to immediately do the search **if** you have exactly
one selection. Exclude untitled buffers in that case. (Ah ... debatable, maybe
should be behind a switch.)

[1] You know, the result buffer can be re-used and then holds the results of
multiple searches.
