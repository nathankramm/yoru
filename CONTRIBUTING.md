# Contributing

## Adding tips

Every tip in `KNOWLEDGE` must be traceable to the installed Omarchy release
under `/usr/share/omarchy` — a script in `bin/`, a Lua file under
`default/hypr/`, a shell function, the menu JSON. Not the manual, not the
GitHub branch, not a blog post, not memory: the manual's hotkeys table lists
`Super + Q` to close a window and it isn't bound; the branch runs ahead of the
packaged release; several widely-circulated cheat sheets have `Super + Space`
and `Super + Alt + Space` backwards. `tools/README.md` says where to look.

The format is `(topic, match, keys, text)`:

```python
("tmux", TERM, "Prefix + z", "Zoom a pane full screen. Same keys back out."),
```

- `match` is `None` for anything that applies everywhere, or a tuple of
  substrings tested against the focused window's `"class title"`.
- Title matches beat class matches, so a tip matching `nvim` outranks one
  matching the terminal it runs inside.
- Keep `text` under about 80 characters. It has to fit a speech bubble.

To check your work:

```bash
python3 yoru.py --list | grep -c "^  "     # count
python3 yoru.py --ask <keyword>            # find it
```

## Behaviour changes

This project has an explicit design position, taken from the research in the
README. Pull requests that make Yoru more talkative, harder to dismiss, or more
observant of the user are unlikely to be merged — that's the road back to
Clippy.

Things that would be very welcome:

- Tips for Omarchy features that aren't covered yet
- The personalization work in the roadmap
- Compositor compatibility beyond Hyprland
