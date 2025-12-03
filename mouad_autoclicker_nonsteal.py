# mouad_autoclicker_nonsteal.py
# Windows-only Tkinter GUI autoclicker with non-stealing background clicks option.
# Save and run: python mouad_autoclicker_nonsteal.py

import ctypes
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

# --------- Windows SendInput & helpers ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_cursor_pos():
    pt = POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        raise OSError("GetCursorPos failed")
    return int(pt.x), int(pt.y)

def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))

# SendInput ctypes structures
PUL = ctypes.POINTER(ctypes.c_ulong)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class INPUT_union(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_union)
    ]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

def _build_mouse_input(flags, x=0, y=0, data=0):
    mi = MOUSEINPUT()
    mi.dx = int(x)
    mi.dy = int(y)
    mi.mouseData = int(data)
    mi.dwFlags = int(flags)
    mi.time = 0
    mi.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = mi
    return inp

def send_input(inp):
    n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
    return n

def send_mouse_event(flags, x=0, y=0, data=0):
    inp = _build_mouse_input(flags, x, y, data)
    send_input(inp)

def screen_to_absolute_virtual(x, y):
    """
    Convert virtual-screen coordinates to SendInput absolute coords (0..65535),
    taking the virtual screen bounds into account.
    """
    left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN

    if width <= 0 or height <= 0:
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        left = 0; top = 0

    # Normalize into 0..65535
    nx = int(((x - left) * 65535) / max(1, (width - 1)))
    ny = int(((y - top) * 65535) / max(1, (height - 1)))
    nx = max(0, min(65535, nx))
    ny = max(0, min(65535, ny))
    return nx, ny

# click function that supports two modes:
# - if keep_cursor True => do NOT move visible cursor (use SendInput absolute)
# - if keep_cursor False => move visible cursor (SetCursorPos) then SendInput down/up (legacy)
def click_at_coords(x, y, keep_cursor):
    """
    Click at virtual-screen coords x,y.
    keep_cursor=True  -> do not move visible cursor (background absolute clicks)
    keep_cursor=False -> physically move cursor then click
    """
    if keep_cursor:
        ax, ay = screen_to_absolute_virtual(int(x), int(y))
        # Move (absolute virtual desk) then down/up to ensure target receives click.
        send_mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)
        # tiny pause
        time.sleep(0.003)
        send_mouse_event(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)
        time.sleep(0.003)
        send_mouse_event(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, ax, ay)
    else:
        # legacy: move the visible cursor then send down/up
        set_cursor_pos(int(x), int(y))
        time.sleep(0.01)
        send_mouse_event(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.01)
        send_mouse_event(MOUSEEVENTF_LEFTUP)

# Virtual screen helper
def get_virtual_screen():
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    w = user32.GetSystemMetrics(78)
    h = user32.GetSystemMetrics(79)
    return left, top, w, h

# --------- Tkinter GUI and logic ----------
class MouadAutoclickerApp:
    def __init__(self, root):
        self.root = root
        root.title("Mouad Autoclicker (Non-stealing option)")
        root.resizable(False, False)

        self.points = {"A1": None, "A2": None, "B": None, "C": None}
        self.running = False
        self.stop_event = threading.Event()
        self.job_thread = None

        frm = ttk.Frame(root, padding=10)
        frm.grid(column=0, row=0)

        # capture buttons and textboxes
        self.text_vars = {}
        cols = [("A1", 0), ("A2", 1), ("B", 2), ("C", 3)]
        for name, col in cols:
            b = ttk.Button(frm, text=f"Set {name}", command=lambda n=name: self.start_overlay_capture(n))
            b.grid(column=col, row=0, padx=6, pady=2)
            tv = tk.StringVar(value="<not set>")
            self.text_vars[name] = tv
            tb = ttk.Entry(frm, textvariable=tv, width=18, state="readonly", justify="center")
            tb.grid(column=col, row=1, padx=6, pady=2)

        # numeric inputs
        ttk.Label(frm, text="Clicks for Action A per cycle:").grid(column=0, row=2, columnspan=2, sticky="w", pady=(10,0))
        self.e_clicks = ttk.Entry(frm, width=8); self.e_clicks.insert(0, "5"); self.e_clicks.grid(column=2, row=2, pady=(10,0))

        ttk.Label(frm, text="Delay between clicks A (ms):").grid(column=0, row=3, columnspan=2, sticky="w")
        self.e_delayA = ttk.Entry(frm, width=8); self.e_delayA.insert(0, "200"); self.e_delayA.grid(column=2, row=3)

        ttk.Label(frm, text="Delay between actions (ms):").grid(column=0, row=4, columnspan=2, sticky="w")
        self.e_between = ttk.Entry(frm, width=8); self.e_between.insert(0, "500"); self.e_between.grid(column=2, row=4)

        ttk.Label(frm, text="Delay between cycles (ms):").grid(column=0, row=5, columnspan=2, sticky="w")
        self.e_cycle = ttk.Entry(frm, width=8); self.e_cycle.insert(0, "1000"); self.e_cycle.grid(column=2, row=5)

        ttk.Label(frm, text="Number of cycles:").grid(column=0, row=6, columnspan=2, sticky="w")
        self.e_cycles = ttk.Entry(frm, width=8); self.e_cycles.insert(0, "3"); self.e_cycles.grid(column=2, row=6)

        # Checkbox for non-stealing mode
        self.keep_cursor_var = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(frm, text="Keep cursor (do not move while clicking — background clicks)", variable=self.keep_cursor_var)
        chk.grid(column=0, row=9, columnspan=4, pady=(10,0), sticky="w")

        # buttons
        btn_test = ttk.Button(frm, text="TEST POINTS", command=self.test_points)
        btn_test.grid(column=0, row=7, pady=(12,0))
        btn_start = ttk.Button(frm, text="START", command=self.start_job)
        btn_start.grid(column=1, row=7, pady=(12,0))
        btn_stop = ttk.Button(frm, text="STOP", command=self.stop_job)
        btn_stop.grid(column=2, row=7, pady=(12,0))

        self.status = tk.StringVar(value="Use 'Set' to capture points (overlay).")
        lbl_status = ttk.Label(frm, textvariable=self.status, wraplength=520)
        lbl_status.grid(column=0, row=8, columnspan=4, pady=(6,0))

    # overlay capture covering virtual screen, captures a single left-click
    def start_overlay_capture(self, name):
        self.status.set(f"Capture mode for {name}: click anywhere (Esc to cancel).")
        left, top, w, h = get_virtual_screen()
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.01)
        except Exception:
            overlay.attributes("-transparentcolor", "white")
        overlay.geometry(f"{w}x{h}+{left}+{top}")
        overlay.config(bg="black")
        overlay.focus_force()

        instr = tk.Label(overlay, text=f"Click to capture {name} (Esc to cancel)", bg="#000000", fg="#ffffff")
        instr.place(x=20, y=20)

        def on_click(event):
            x, y = int(event.x_root), int(event.y_root)
            self.points[name] = {"X": x, "Y": y}
            self.text_vars[name].set(f"X:{x} Y:{y}")
            self.status.set(f"{name} captured: X:{x} Y:{y}")
            overlay.destroy()
            self.show_preview_dot(x, y, 0.35)

        def on_key(event):
            if event.keysym == "Escape":
                self.status.set("Capture cancelled.")
                overlay.destroy()

        overlay.bind("<Button-1>", on_click)
        overlay.bind("<Key>", on_key)
        overlay.grab_set()
        overlay.mainloop()

    def show_preview_dot(self, x, y, duration_s=0.35):
        try:
            dot = tk.Toplevel(self.root)
            dot.overrideredirect(True)
            dot.attributes("-topmost", True)
            dot.geometry(f"6x6+{x-3}+{y-3}")
            frame = tk.Frame(dot, width=6, height=6, bg="red")
            frame.pack()
            dot.after(int(duration_s * 1000), dot.destroy)
        except Exception:
            pass

    def test_points(self):
        s = ""
        for k in ("A1", "A2", "B", "C"):
            p = self.points.get(k)
            if p:
                s += f"{k} => X:{p['X']} Y:{p['Y']}\n"
            else:
                s += f"{k} => <not set>\n"
        messagebox.showinfo("Captured Points", s)

    def validate_points(self):
        for k in ("A1", "A2", "B", "C"):
            p = self.points.get(k)
            if not p or "X" not in p or "Y" not in p:
                self.status.set(f"Missing {k}. Use Set {k} to capture.")
                return False
        return True

    def start_job(self):
        if self.running:
            self.status.set("Already running.")
            return
        if not self.validate_points():
            return
        try:
            clicksA = int(self.e_clicks.get())
            delayA = int(self.e_delayA.get()) / 1000.0
            between = int(self.e_between.get()) / 1000.0
            cycle_wait = int(self.e_cycle.get()) / 1000.0
            cycles = int(self.e_cycles.get())
        except Exception:
            messagebox.showerror("Invalid input", "Please enter valid integer values for delays and counts.")
            return

        self.stop_event.clear()
        # pass keep_cursor mode by reading checkbox inside worker for each click
        self.job_thread = threading.Thread(target=self._job_worker,
                                           args=(self.points.copy(), clicksA, delayA, between, cycle_wait, cycles),
                                           daemon=True)
        self.running = True
        self.job_thread.start()
        self.status.set("Running... Click STOP to cancel. You can continue using your laptop.")

    def stop_job(self):
        if self.running:
            self.stop_event.set()
            self.status.set("Stopping... waiting for worker to exit.")
            self.running = False
        else:
            self.status.set("No running job.")

    def _job_worker(self, p, clicksA, delayA, between, cycle_wait, cycles):
        try:
            for c in range(1, cycles + 1):
                if self.stop_event.is_set():
                    break
                for i in range(1, clicksA + 1):
                    if self.stop_event.is_set():
                        break
                    keep_cursor = self.keep_cursor_var.get()
                    click_at_coords(p["A1"]["X"], p["A1"]["Y"], keep_cursor)
                    self._sleep_with_stop(delayA)
                    if self.stop_event.is_set():
                        break
                    keep_cursor = self.keep_cursor_var.get()
                    click_at_coords(p["A2"]["X"], p["A2"]["Y"], keep_cursor)
                    self._sleep_with_stop(delayA)
                if self.stop_event.is_set():
                    break
                self._sleep_with_stop(between)
                if self.stop_event.is_set():
                    break
                keep_cursor = self.keep_cursor_var.get()
                click_at_coords(p["B"]["X"], p["B"]["Y"], keep_cursor)
                self._sleep_with_stop(between)
                if self.stop_event.is_set():
                    break
                keep_cursor = self.keep_cursor_var.get()
                click_at_coords(p["C"]["X"], p["C"]["Y"], keep_cursor)
                self._sleep_with_stop(cycle_wait)
        except Exception as ex:
            self.root.after(0, lambda: messagebox.showerror("Worker error", str(ex)))
        finally:
            self.running = False
            self.stop_event.clear()
            self.root.after(0, lambda: self.status.set("Stopped."))

    def _sleep_with_stop(self, seconds, step=0.02):
        total = 0.0
        while total < seconds:
            if self.stop_event.is_set():
                break
            time.sleep(step)
            total += step

def main():
    root = tk.Tk()
    app = MouadAutoclickerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
