"""Expose Boxflat's real controls to QML without showing a GTK window.

The original widgets retain their callbacks, conversions, capability checks,
and calibration state machines. Only their presentation crosses this adapter.
"""
import math
import re
from gi.repository import Gtk, Adw
from boxflat.widgets import (
    BoxflatSliderRow, BoxflatSwitchRow, BoxflatToggleButtonRow,
    BoxflatComboRow, BoxflatEqRow, BoxflatNewColorPickerRow,
    BoxflatDialogRow, BoxflatLevelRow, BoxflatLabelRow, BoxflatButtonRow,
    BoxflatButtonLevelRow, BoxflatAdvanceRow,
)


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def descendants(widget, kind):
    for child in children(widget):
        if isinstance(child, kind):
            yield child
        else:
            yield from descendants(child, kind)


def plain(text):
    return re.sub(r"<[^>]+>", "", text or "")


class Model:
    def __init__(self):
        self.objects = {}
        self.live_readers = {}

    def key(self, widget):
        key = str(id(widget))
        self.objects[key] = widget
        return key

    def row(self, row):
        value = dict(id=self.key(row), title=plain(row.get_title()),
                     subtitle=plain(row.get_subtitle()) if hasattr(row, "get_subtitle") else "",
                     enabled=row.is_sensitive(), visible=row.get_visible(), kind="label")
        if isinstance(row, BoxflatEqRow):
            value.update(kind="equalizer", options=[b.get_label() for b in row._buttons],
                         value=next((i for i,b in enumerate(row._buttons) if b.get_active()), -1),
                         sliders=[dict(value=s.get_value(), min=s.get_adjustment().get_lower(),
                                       max=s.get_adjustment().get_upper(), step=s.get_adjustment().get_step_increment(),
                                       label=plain(row._slider_labels[i].get_text()), enabled=s.is_sensitive())
                                  for i,s in enumerate(row._sliders)])
        elif isinstance(row, BoxflatSliderRow):
            value.update(kind="slider", value=row.get_raw_value(), min=row._range_start,
                         max=row._range_end, step=row._increment, suffix=row._suffix)
        elif isinstance(row, BoxflatSwitchRow):
            value.update(kind="switch", value=row._switch.get_active())
        elif isinstance(row, BoxflatComboRow):
            model = row.get_model()
            value.update(kind="choice", value=row.get_selected(),
                         options=[model.get_string(i) for i in range(model.get_n_items())])
        elif isinstance(row, BoxflatToggleButtonRow):
            value.update(kind="choice", options=[b.get_label().strip() for b in row._buttons],
                         value=next((i for i,b in enumerate(row._buttons) if b.get_active()), -1))
        elif isinstance(row, BoxflatNewColorPickerRow):
            value.update(kind="colors", colors=["#" + "".join(f"{v:02x}" for v in row.get_value(i))
                                                for i in range(len(row._colors))])
        elif isinstance(row, BoxflatDialogRow):
            value.update(kind="group", rows=[self.row(s) for s in row._switches])
        elif isinstance(row, Adw.ExpanderRow):
            # Adwaita's internal header is another ActionRow. Export only the
            # application's rows, including a Generic Devices remove button.
            nested = [s for s in descendants(row, Adw.PreferencesRow)
                      if type(s) is not Adw.ActionRow]
            value.update(kind="group", rows=[self.row(s) for s in nested])
        elif isinstance(row, Adw.EntryRow):
            value.update(kind="entry", value=row.get_text())
        elif isinstance(row, BoxflatLevelRow):
            value.update(kind="level", value=row.get_value(), max=row._max_value)
        elif isinstance(row, BoxflatLabelRow):
            value.update(value=plain(row.get_label()))
            if row.get_activatable(): value["kind"] = "action"
        elif isinstance(row, (Adw.ButtonRow, BoxflatAdvanceRow)):
            value["kind"] = "action"
        elif isinstance(row, BoxflatButtonRow):
            value["kind"] = "buttons"
        else:
            raise TypeError(f"Unmapped Boxflat control: {type(row).__name__} {value['title']}")
        if isinstance(row, (BoxflatButtonRow, BoxflatButtonLevelRow)):
            value["buttons"] = [dict(id=self.key(b), label=b.get_label(), enabled=b.is_sensitive())
                                for b in children(row._box) if isinstance(b, Gtk.Button)]
        return value

    def groups(self, widget):
        if isinstance(widget, Adw.NavigationView):
            return self.groups(widget.get_visible_page())
        out = []
        for group in descendants(widget, Adw.PreferencesGroup):
            suffix = group.get_header_suffix()
            rows = [self.row(row) for row in descendants(group, Adw.PreferencesRow)]
            out.append(dict(id=self.key(group), title=plain(group.get_title()),
                            description=plain(group.get_description()), visible=group.get_visible(),
                            rows=rows, add=self.key(suffix) if isinstance(suffix, Gtk.Button) else ""))
        return out

    def pages(self, panel):
        if panel._current_stack:
            pages = panel._current_stack.get_pages()
            return [dict(title=pages.get_item(i).get_title(),
                         groups=self.groups(pages.get_item(i).get_child())) for i in range(pages.get_n_items())]
        return [dict(title="", groups=self.groups(panel.content))]

    def track_live(self, pages):
        """Separate input readings from settings; retain getters for fast samples."""
        readers = {}
        values = {}

        def visit(row):
            widget = self.objects[row["id"]]
            if row["kind"] in ("level", "label") and isinstance(widget, (BoxflatLevelRow, BoxflatLabelRow)):
                readers[row["id"]] = widget.get_value if isinstance(widget, BoxflatLevelRow) else lambda w=widget: plain(w.get_label())
                values[row["id"]] = row.pop("value")
                row["live"] = True
            for child in row.get("rows", []): visit(child)

        for page in pages:
            for group in page["groups"]:
                for row in group["rows"]: visit(row)
        self.live_readers = readers
        return values

    def live_values(self):
        return {key: read() for key, read in self.live_readers.items()}

    def act(self, key, action, value=None, index=0):
        widget = self.objects.get(str(key))
        if widget is None or not widget.is_sensitive():
            raise ValueError("This control is unavailable. Refresh the panel.")
        if action == "click":
            if isinstance(widget, Gtk.Button): widget.emit("clicked")
            elif isinstance(widget, Adw.ActionRow) and widget.get_activatable(): widget.emit("activated")
            elif isinstance(widget, Adw.ButtonRow): widget.emit("activated")
            else: raise ValueError("Control has no action")
            return
        if isinstance(widget, Adw.EntryRow) and action == "set":
            if not isinstance(value, str) or len(value) > 160: raise ValueError("Text is too long")
            # Preset names must be basenames; Boxflat joins these with its path.
            if "name" in widget.get_title().lower() and ("/" in value or "\\" in value or value in [".", ".."]):
                raise ValueError("Names cannot contain a path")
            widget.set_text(value)
            return
        if isinstance(widget, BoxflatNewColorPickerRow) and action == "color":
            if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value): raise ValueError("Invalid colour")
            if type(index) is not int or not 0 <= index < len(widget._colors): raise ValueError("Invalid LED")
            from gi.repository import Gdk
            rgba = Gdk.RGBA(); rgba.parse(value)
            widget._set_led_value(rgba, index, False)
            return
        if not isinstance(value, (int, float, bool)) or not math.isfinite(value): raise ValueError("Expected a number")
        if isinstance(widget, BoxflatEqRow) and action == "slider":
            if type(index) is not int or not 0 <= index < len(widget._sliders): raise ValueError("Invalid slider")
            slider = widget._sliders[index]
            if not slider.is_sensitive(): raise ValueError("Slider unavailable")
            self.set_slider(slider, value)
        elif isinstance(widget, BoxflatSliderRow) and action == "set": self.set_slider(widget._slider, value)
        elif isinstance(widget, BoxflatSwitchRow) and action == "set": widget._switch.set_active(bool(value))
        elif isinstance(widget, BoxflatToggleButtonRow) and action == "set":
            if int(value) != value or not 0 <= value < len(widget._buttons): raise ValueError("Invalid option")
            widget._buttons[int(value)].set_active(True)
        elif isinstance(widget, BoxflatComboRow) and action == "set":
            if int(value) != value or not 0 <= value < widget.get_model().get_n_items(): raise ValueError("Invalid option")
            widget.set_selected(int(value))
        else: raise ValueError("Unsupported action")

    @staticmethod
    def set_slider(slider, value):
        adj = slider.get_adjustment()
        if not adj.get_lower() <= value <= adj.get_upper(): raise ValueError("Value outside the allowed range")
        slider.set_value(value)
