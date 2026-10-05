#!/usr/bin/env python3
"""Make an offscreen-capable copy of Omarchy's Ui/KeyboardPanel.qml.

KeyboardPanel is a layer-shell PanelWindow, which the offscreen Qt platform
cannot create. This rewrites only the window plumbing (PanelWindow ->
FloatingWindow sized to the screen; drops layer-shell props, the input mask and
the per-output dismissal twins). The card itself (BorderSurface, its colors,
border, padding, radius, and cardOrigin placement) is kept verbatim, so the
captured card is the production chrome.
"""
import re
import sys

src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()


def drop_block(text, start_pattern):
    m = re.search(start_pattern, text, re.M)
    if not m:
        raise SystemExit(f"pattern not found: {start_pattern}")
    i = text.index("{", m.start())
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                end = text.index("\n", j) + 1
                return text[:m.start()] + text[end:]
    raise SystemExit("unbalanced block")


text = re.sub(r"^PanelWindow \{", "FloatingWindow {\n  implicitWidth: screenW > 0 ? screenW : 1600\n  implicitHeight: screenH > 0 ? screenH : 1000", text, count=1, flags=re.M)
text = re.sub(r"^\s*WlrLayershell\.[^\n]*\n(?:\s+\? [^\n]*\n\s+: [^\n]*\n)?", "", text, flags=re.M)
text = re.sub(r"^  exclusionMode: [^\n]*\n", "", text, flags=re.M)
text = drop_block(text, r"^  anchors \{")
text = drop_block(text, r"^  mask: Region \{")
text = drop_block(text, r"^  Variants \{")
open(dst, "w").write(text)
