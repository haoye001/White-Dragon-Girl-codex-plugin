"""Rounded, dynamically sized speech bubble with a transparent exterior."""
import tkinter as tk

KEY = '#ff00ff'


class SpeechBubble:
    def __init__(self, owner):
        self.owner = owner
        self.window = tk.Toplevel(owner)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        self.window.configure(bg=KEY)
        self.window.wm_attributes('-transparentcolor', KEY)
        self.canvas = tk.Canvas(self.window, bg=KEY, highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill='both', expand=True)
        self.active = False
        self.height = 90
        self.text = ''

    def show(self, text):
        self.text = text
        self.canvas.delete('all')
        # Keep very long responses readable; full answers remain in the Codex chat.
        shown = text if len(text) <= 450 else text[:447]+'…'
        item = self.canvas.create_text(20, 15, text=shown, anchor='nw', width=260,
                                      font=('Microsoft YaHei', 10), fill='#4a365b', justify='left')
        box = self.canvas.bbox(item)
        self.height = max(62, box[3]+18)+16
        bottom = self.height-18
        radius = 16
        points = [radius, 3, 300-radius, 3, 297, 3, 297, radius,
                  297, bottom-radius, 297, bottom, 300-radius, bottom,
                  radius, bottom, 3, bottom, 3, bottom-radius, 3, radius, 3, 3]
        body = self.canvas.create_polygon(points, smooth=True, splinesteps=24,
                                          fill='#fff8ff', outline='#cdb7df', width=2)
        tail = self.canvas.create_polygon(194,bottom-2, 211,bottom+15, 224,bottom-2,
                                          fill='#fff8ff', outline='#cdb7df', width=2)
        seam = self.canvas.create_line(195,bottom-1, 223,bottom-1, fill='#fff8ff', width=3)
        self.canvas.tag_raise(item)
        self.canvas.configure(width=300, height=self.height)
        self.active = True
        self.position()

    def position(self):
        if not self.active or not self.owner.winfo_viewable():
            self.window.withdraw()
            return
        x = max(0, min(self.owner.winfo_x(), self.owner.winfo_screenwidth()-300))
        y = self.owner.winfo_y()-self.height+18
        y = max(0, min(y, self.owner.winfo_screenheight()-self.height))
        self.window.geometry(f'300x{self.height}+{x}+{y}')
        self.window.deiconify()

    def hide(self):
        self.active = False
        self.window.withdraw()

    def withdraw(self):
        self.window.withdraw()
