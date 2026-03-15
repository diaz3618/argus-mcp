"""Debug launcher to trace focus changes in Textual TUI."""

from __future__ import annotations

import traceback

from textual.screen import Screen

_TRACE_FILE = "/tmp/focus_trace.log"


def _write_trace(msg: str) -> None:
    with open(_TRACE_FILE, "a") as f:
        f.write(msg + "\n")


# Clear trace file on import
with open(_TRACE_FILE, "w") as f:
    f.write("=== Focus trace started ===\n")

# Trace _update_auto_focus
_orig_update_auto_focus = Screen._update_auto_focus


def _traced_update_auto_focus(self):
    cls = type(self)
    in_dict = "AUTO_FOCUS" in self.__dict__
    dict_val = self.__dict__.get("AUTO_FOCUS", "NOT_IN_DICT")
    class_val = cls.__dict__.get("AUTO_FOCUS", "NOT_IN_CLASS")
    # Check all classes in MRO
    mro_vals = {
        c.__name__: c.__dict__.get("AUTO_FOCUS", "MISSING")
        for c in cls.__mro__
        if "AUTO_FOCUS" in c.__dict__
    }
    auto_focus = self.app.AUTO_FOCUS if self.AUTO_FOCUS is None else self.AUTO_FOCUS
    import sys

    mod = sys.modules.get(cls.__module__)
    mod_file = getattr(mod, "__file__", "NO_FILE") if mod else "NO_MODULE"
    _write_trace(
        f"_update_auto_focus on {cls.__name__}: "
        f"self.AUTO_FOCUS={self.AUTO_FOCUS!r}, "
        f"in_instance_dict={in_dict}, dict_val={dict_val!r}, "
        f"class_val={class_val!r}, "
        f"mro_vals={mro_vals!r}, "
        f"cls_id={id(cls)}, "
        f"module={cls.__module__}, "
        f"mod_file={mod_file!r}, "
        f"app.AUTO_FOCUS={self.app.AUTO_FOCUS!r}, "
        f"resolved={auto_focus!r}, focused={self.focused}"
    )
    _orig_update_auto_focus(self)
    _write_trace(f"  -> After: focused={self.focused}")


Screen._update_auto_focus = _traced_update_auto_focus

# Trace ALL set_focus calls (not just tools-search)
_orig_set_focus = Screen.set_focus


def _traced_set_focus(self, widget, animate=True):
    wid = getattr(widget, "id", None) if widget else None
    wclass = type(widget).__name__ if widget else None
    stack = "".join(traceback.format_stack()[-4:-1])
    _write_trace(f"SET_FOCUS({wclass}#{wid}) on {self.__class__.__name__}\n{stack}")
    return _orig_set_focus(self, widget, animate)


Screen.set_focus = _traced_set_focus

# Now import and configure the real app
from mods.tui_launcher import app as _make_app  # noqa: E402


def app():
    return _make_app()
