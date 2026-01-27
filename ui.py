import tkinter as tk
from tkinter import ttk


class SchedulerUI:
    """Placeholder UI not yet adapted to the new campaign/mission workflow."""

    def __init__(self, *_args, **_kwargs):
        self.root = tk.Tk()
        self.root.title("Scheduler UI (placeholder)")
        label = ttk.Label(self.root, text="UI not implemented for the new model. Use CLI.")
        label.pack(padx=20, pady=20)

    def run(self) -> None:
        self.root.mainloop()
