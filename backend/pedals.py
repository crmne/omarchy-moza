"""Guided pedal calibration and reversible range capture, outside Boxflat."""
import math
import threading
import time

from gi.repository import GLib, Gtk
from boxflat.widgets import BoxflatCalibrationRow, BoxflatLevelRow


class PedalRange:
    """Read back range writes and restore the original limits on failure."""

    def __init__(self, cm, pedal):
        self.cm = cm
        self.prefix = f"pedals-{pedal}"
        self.original = None
        self.changed = False

    def read(self, name, maximum=100):
        for _ in range(3):
            value = self.cm.get_setting(f"{self.prefix}-{name}")
            if type(value) is int and 0 <= value <= maximum:
                return value
        raise ValueError("Pedal did not respond. Check its connection and try again.")

    def write(self, name, value):
        self.cm.set_setting(value, f"{self.prefix}-{name}")
        for _ in range(3):
            if self.read(name) == value:
                return
            time.sleep(.05)
        raise ValueError("Pedal did not confirm the new range. Check its connection.")

    def prepare(self):
        low, high = self.read("min"), self.read("max")
        if low >= high:
            raise ValueError("Invalid pedal range. Set Range Start below Range End on the Pedals page.")
        self.original = low, high
        self.changed = True
        self.full_range()

    def full_range(self):
        # Widen before narrowing, so intermediate ranges remain valid.
        self.write("min", 0)
        self.write("max", 100)

    def save(self, endpoint):
        # Read only AFTER reopening the full range. Never reuse the clipped
        # HID bar or a reading taken with the previous shortened range.
        raw = self.read("output", 65535)
        value = math.floor(raw * 100 / 65535) if endpoint == "max" else math.ceil(raw * 100 / 65535)
        low, high = self.original
        if (endpoint == "max" and value <= low) or (endpoint == "min" and value >= high):
            raise ValueError("That position would leave no pedal travel. Previous limits will be restored.")
        self.write("max", value if endpoint == "max" else high)
        self.write("min", value if endpoint == "min" else low)
        self.changed = False
        return value

    def restore(self):
        if not self.changed:
            return
        self.write("min", 0)
        self.write("max", self.original[1])
        self.write("min", self.original[0])
        self.changed = False


class PedalControls:
    """Keep GTK updates on the main loop and device I/O on one worker."""

    def __init__(self, model, panels, cm, hid, notice):
        self.cm, self.notice = cm, notice
        self.hid = hid
        self.controls = {}
        self.inputs = {}
        self.result_timers = {}
        self.active = None
        self.phase = "idle"
        self.request = threading.Event()
        self.choice = "cancel"
        self.worker = None
        self.closed = False
        for pedal in ("throttle", "brake", "clutch"):
            hid.subscribe(pedal, self.sample, pedal)
        model.before_action = self.before_action
        # Boxflat queues insertion of its rows on the GTK main loop.
        GLib.idle_add(self.bind_panels, model, panels)

    def bind_panels(self, model, panels):
        for page in model.pages(panels["Home"]):
            for group in page["groups"]:
                for data in group["rows"]:
                    pedal = data["title"].split(" ")[0].lower()
                    if data["title"] == f"{pedal.title()} input" and pedal in ("throttle", "brake", "clutch"):
                        row = model.objects[data["id"]]
                        # Upstream disables both buttons at 0% and 100%. Those
                        # are exactly the positions from which recapture must work.
                        row._bar.disconnect_by_func(row._disable_buttons)
                        self.bind(row, pedal, "range")
        pedal_pages = panels["Pedals"]._current_stack.get_pages()
        for index, page in enumerate(model.pages(panels["Pedals"])):
            for group in page["groups"]:
                for data in group["rows"]:
                    row = model.objects[data["id"]]
                    if isinstance(row, BoxflatCalibrationRow):
                        self.bind(row, page["title"].lower(), "calibration")
            self.arrange_page(model, page, pedal_pages.get_item(index).get_child())
        return False

    def arrange_page(self, model, page, widget):
        groups = {group["title"]: group for group in page["groups"]}
        range_data = groups[f"{page['title']} Range"]
        range_group = model.objects[range_data["id"]]
        curve_group = model.objects[groups[f"{page['title']} Curve"]["id"]]
        other_group = model.objects[groups["Misc"]["id"]]
        calibration, _ = self.controls[page["title"].lower(), "calibration"]

        other_group.remove(calibration)
        range_rows = [model.objects[row["id"]] for row in range_data["rows"]]
        for row in range_rows:
            range_group.remove(row)
        input_row = BoxflatLevelRow(f"{page['title']} input", max_value=65_534)
        self.hid.subscribe(page["title"].lower(), input_row.set_value)
        self.cm.subscribe_connected("pedals-throttle-dir", input_row.set_active, 1)
        for row in [input_row, calibration, *range_rows]:
            range_group.add(row)
        range_group.set_title("Calibration and range")
        curve_group.set_title("Response curve")
        other_group.set_title("Other settings")

        original_groups = [model.objects[group["id"]] for group in page["groups"]]
        for group in original_groups:
            widget.remove(group)
        widget.add(range_group)
        widget.add(curve_group)
        for group in original_groups:
            if group not in (range_group, curve_group):
                widget.add(group)

    def bind(self, row, pedal, mode):
        for child in list(self.children(row._box)):
            if isinstance(child, Gtk.Button):
                row._box.remove(child)
        buttons = {}
        for action, label in (("min", "Set min"), ("max", "Set max")) if mode == "range" else (("calibration", "Calibrate"),):
            buttons[action] = row.add_button(label, self.start, pedal, action)
        buttons["cancel"] = row.add_button("Cancel", self.cancel)
        buttons["cancel"].set_visible(False)
        self.controls[pedal, mode] = row, buttons
        row.set_subtitle(self.idle_subtitle(mode))

    @staticmethod
    def idle_subtitle(mode):
        return "Release the pedal before starting. Calibration resets the range to 0–100%." if mode == "calibration" else ""

    @staticmethod
    def children(widget):
        child = widget.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def sample(self, value, pedal):
        self.inputs[pedal] = value, time.monotonic()

    def before_action(self, widget):
        if not self.active:
            return
        pedal, mode = self.active
        _, buttons = self.controls[pedal, "calibration" if mode == "calibration" else "range"]
        if widget not in buttons.values():
            raise ValueError(f"Finish or cancel {pedal} setup before changing other settings.")

    def start(self, pedal, mode):
        if self.closed:
            return
        if self.active:
            if self.active == (pedal, mode) and self.phase == "capture":
                self.choice = "save"
                self.request.set()
                self.render("saving", "Saving the new limit…")
            return
        self.clear_results()
        self.active = pedal, mode
        self.choice = "cancel"
        self.request.clear()
        self.notice("")
        self.render("preparing", "Reading previous limits and reopening the full pedal range…")
        self.worker = threading.Thread(target=self.run, args=(pedal, mode), daemon=True)
        self.worker.start()

    def cancel(self):
        self.choice = "cancel"
        self.request.set()
        self.render("stopping", "Stopping and restoring previous range limits…")

    def render(self, phase, text):
        if self.closed or not self.active:
            return False
        if self.request.is_set() and phase in ("preparing", "capture", "recording"):
            return False
        self.phase = phase
        pedal, mode = self.active
        row, buttons = self.controls[pedal, "calibration" if mode == "calibration" else "range"]
        row.set_subtitle(text)
        for action, button in buttons.items():
            button.set_visible(action in (mode, "cancel"))
            button.set_sensitive((action == "cancel" and phase not in ("saving", "stopping")) or phase == "capture")
            if action == mode:
                button.set_label(f"Save {mode}" if phase == "capture" else {
                    "preparing": "Preparing…", "recording": "Recording…",
                    "saving": "Saving…", "stopping": "Stopping…",
                }[phase])
        return False

    def post(self, phase, text):
        GLib.idle_add(self.render, phase, text)

    def countdown(self, seconds, phase, instruction, pedal, samples=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            remaining = math.ceil(end - time.monotonic())
            reading = self.inputs.get(pedal)
            fresh = reading and time.monotonic() - reading[1] < 1
            feedback = f" Input: {round(reading[0] * 100 / 65534)}%." if fresh else " Waiting for pedal input."
            if samples is not None and fresh:
                samples.append(reading[0])
            self.post(phase, f"{instruction} {remaining}s remaining.{feedback}")
            if self.request.wait(min(.1, max(0, end - time.monotonic()))):
                return False
        return True

    def run(self, pedal, mode):
        session = PedalRange(self.cm, pedal)
        started = False
        success = False
        result = ""
        try:
            session.prepare()
            if mode == "calibration":
                if not self.countdown(3, "preparing", f"Keep {pedal} released. Recording starts in", pedal):
                    result = "Calibration cancelled. Previous range limits restored."
                else:
                    started = True
                    self.cm.set_setting(1, f"pedals-{pedal}-calibration-start", True)
                    samples = []
                    completed = self.countdown(7, "recording", f"Press {pedal} fully, then release NOW. Recording:", pedal, samples)
                    self.cm.set_setting(0, f"pedals-{pedal}-calibration-stop", True)
                    started = False
                    if not completed:
                        result = "Recording stopped. Previous range limits restored. Run calibration again before driving."
                    elif not samples or max(samples) - min(samples) < 655:
                        result = "Recording ended, but no pedal movement was detected. Previous range limits restored. Try calibration again."
                    else:
                        session.full_range()
                        session.changed = False
                        success = True
                        result = "Calibration finished. Check the input above: release for 0%, press fully for 100%."
            else:
                instruction = f"Hold {pedal} at the desired {mode} position, then choose Save {mode}."
                self.countdown(30, "capture", instruction, pedal)
                if self.request.is_set() and self.choice == "save":
                    value = session.save(mode)
                    success = True
                    result = f"{pedal.title()} {mode} saved at {value}%. Test the pedal, or choose Set {mode} to adjust again."
                else:
                    result = "Limit capture cancelled. Previous range limits restored."
        except Exception as error:
            result = str(error)
        finally:
            if started:
                try:
                    self.cm.set_setting(0, f"pedals-{pedal}-calibration-stop", True)
                except Exception:
                    success = False
                    result += " Could not stop recording. Reconnect the pedals and recalibrate."
            try:
                session.restore()
            except Exception:
                success = False
                result = result.replace("Previous range limits restored.", "").replace("Previous limits will be restored.", "")
                result += " Could not restore previous limits. Reconnect and check Range Start and Range End before driving."
            GLib.idle_add(self.finish, result, success)

    def finish(self, result, success=False):
        if self.closed or not self.active:
            return False
        pedal, mode = self.active
        row, buttons = self.controls[pedal, "calibration" if mode == "calibration" else "range"]
        row.set_subtitle(result)
        for action, button in buttons.items():
            button.set_visible(action != "cancel")
            button.set_sensitive(True)
            button.set_label("Calibrate again" if action == "calibration" else "Cancel" if action == "cancel" else f"Set {action}")
        message = result if result.startswith(pedal.title()) else f"{pedal.title()}: {result}"
        self.notice(message)
        self.active = None
        self.phase = "idle"
        if success:
            key = pedal, "calibration" if mode == "calibration" else "range"
            source = GLib.timeout_add(8000, self.expire_result, key)
            self.result_timers[key] = source, result, message
        return False

    def expire_result(self, key):
        entry = self.result_timers.pop(key, None)
        if entry is None or self.closed:
            return False
        _, result, message = entry
        row, buttons = self.controls[key]
        if row.get_subtitle() == result:
            row.set_subtitle(self.idle_subtitle(key[1]))
            if key[1] == "calibration":
                buttons["calibration"].set_label("Calibrate")
        # Do not dismiss a newer preset notification or other message.
        self.notice("", message)
        return False

    def clear_results(self):
        for key, (source, _, _) in list(self.result_timers.items()):
            GLib.source_remove(source)
            self.expire_result(key)

    def shutdown(self):
        self.closed = True
        self.clear_results()
        self.choice = "cancel"
        self.request.set()
        if self.worker:
            self.worker.join()
