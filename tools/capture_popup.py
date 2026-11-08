"""Show the real notification card (popup.py) and save a picture of just that window.

    python tools/capture_popup.py <path-to-popup.py> <out.png> "title" "message"

The capture runs in a separate process while the card keeps drawing (a blocking capture would deadlock it).
"""
import ctypes
import runpy
import subprocess
import sys
import tkinter as tk
from pathlib import Path

popup, out, title, message = sys.argv[1:5]
script = Path(__file__).with_name("capture_window.ps1")
real_tk = tk.Tk


class CapturingTk(real_tk):
    def mainloop(self, n=0):
        def start():
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            self.proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                          str(script), "-Out", out, "-Hwnd", str(hwnd)])

        def finish():
            if self.proc.poll() is None:
                self.after(200, finish)
            else:
                self.destroy()
        self.after(600, start)
        self.after(1500, finish)
        super().mainloop(n)


tk.Tk = CapturingTk
sys.argv = [popup, title, message]
runpy.run_path(popup, run_name="__main__")
print("saved" if Path(out).exists() else "capture failed", out)
