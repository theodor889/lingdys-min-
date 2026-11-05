"""Skriveflyt desktop interface."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from engine import WritingEngine
from windows_input import INPUT, KEYBDINPUT, WindowsTypingAssistant, log


BG = "#F4F6FA"
WHITE = "#FFFFFF"
INK = "#172033"
MUTED = "#69758A"
LINE = "#E5EAF2"
BLUE = "#4263EB"
BLUE_DARK = "#3451CF"
MINT = "#DDF8EF"
GREEN = "#147D61"
NAVY = "#17223B"
PURPLE = "#7357E8"


class SkriveflytApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Skriveflyt — skrivehjelp for Windows")
        self.root.geometry("1160x800")
        self.root.minsize(1000, 700)
        self.root.configure(bg=BG)
        self.engine = WritingEngine()
        # The keyboard hook runs on its own thread. It must never call Tk
        # directly, so it drops messages here and Tk picks them up.
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.assistant = WindowsTypingAssistant(
            self._queue_suggestions,
            self._queue_hide,
            self._queue_learned,
            self._queue_read_selection,
            self._queue_dictate,
            self._queue_toggle_language,
            self._queue_pause,
            self._queue_sleep,
            self._queue_wake,
        )
        self._speech_paused = False
        self._toast_id = 0
        self._speech_proc: subprocess.Popen | None = None
        self.live_active = False
        self.active_page = "Oversikt"
        self.live_overlay: tk.Toplevel | None = None
        self.live_overlay_hwnd = 0
        self._demo_suggestions: list[str] = []
        self._page: tk.Frame | None = None
        self._setup_style()
        self._build_shell()
        self.show_page("Oversikt")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(30, self._drain_ui_queue)
        self.root.after(250, self._create_live_overlay)
        self.root.after(450, self.start_live)
        self.root.after(800, self._first_run_autostart)
        if self.engine.language == "en":
            self.root.after(900, lambda: self.assistant.switch_input_language("en"))

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TEntry", fieldbackground=WHITE, foreground=INK, padding=10,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10),
                        foreground=WHITE, background=BLUE, padding=(14, 9), borderwidth=0)
        style.map("Primary.TButton", background=[("active", BLUE_DARK), ("disabled", "#AAB5D4")])
        style.configure("Soft.TButton", font=("Segoe UI Semibold", 9),
                        foreground=INK, background="#EDF1F8", padding=(11, 8), borderwidth=0)
        style.map("Soft.TButton", background=[("active", "#E0E7F2")])

    def _build_shell(self) -> None:
        self.shell = tk.Frame(self.root, bg=BG)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.shell, bg=WHITE, width=226,
                                highlightbackground=LINE, highlightthickness=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=WHITE)
        brand.pack(fill="x", padx=22, pady=(24, 32))
        mark = tk.Label(brand, text="S", bg=PURPLE, fg=WHITE,
                        font=("Segoe UI Semibold", 16), width=2, height=1)
        mark.pack(side="left", padx=(0, 10))
        brand_text = tk.Frame(brand, bg=WHITE)
        brand_text.pack(side="left")
        tk.Label(brand_text, text="skriveflyt", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(brand_text, text="LESING  ·  SKRIVING", bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(1, 0))

        tk.Label(self.sidebar, text="MENY", bg=WHITE, fg="#97A2B5",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=24, pady=(0, 9))
        self.nav_buttons: dict[str, tk.Button] = {}
        for name, glyph in (("Oversikt", "⌂"), ("Mine ord", "Aa"), ("Innstillinger", "⚙")):
            button = tk.Button(
                self.sidebar, text=f"  {glyph}     {name}", anchor="w", bd=0,
                relief="flat", cursor="hand2", padx=13, pady=11,
                font=("Segoe UI Semibold", 10), command=lambda page=name: self.show_page(page),
            )
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[name] = button

        bottom = tk.Frame(self.sidebar, bg="#F7F8FC", highlightbackground=LINE, highlightthickness=1)
        bottom.pack(side="bottom", fill="x", padx=14, pady=18)
        tk.Label(bottom, text="🔒  Lokale rettinger", bg="#F7F8FC", fg=INK,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(bottom, text="Rettelser lagres på PC-en.", bg="#F7F8FC", fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(0, 12))

        self.content = tk.Frame(self.shell, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def show_page(self, name: str) -> None:
        self.active_page = name
        self.start_button = None
        self.settings_toggle = None
        for page, button in self.nav_buttons.items():
            active = page == name
            button.configure(bg="#EEF0FF" if active else WHITE,
                             fg=PURPLE if active else MUTED,
                             activebackground="#E6E9FF" if active else "#F4F6FA")
        if self._page:
            self._page.destroy()
        self._page = tk.Frame(self.content, bg=BG)
        self._page.pack(fill="both", expand=True, padx=30, pady=24)
        if name == "Oversikt":
            self._build_dashboard()
        elif name == "Mine ord":
            self._build_my_words()
        else:
            self._build_settings()
        self._update_status()

    def _page_heading(self, title: str, subtitle: str) -> tk.Frame:
        header = tk.Frame(self._page, bg=BG)
        header.pack(fill="x", pady=(0, 19))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 21)).pack(anchor="w")
        tk.Label(left, text=subtitle, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        self.status_pill = tk.Label(header, text="●  Starter …", bg="#EDF0F5", fg=MUTED,
                                    font=("Segoe UI Semibold", 9), padx=12, pady=8)
        self.status_pill.pack(side="right", anchor="n", pady=(3, 0))
        return header

    def _card(self, parent: tk.Widget, **kwargs) -> tk.Frame:
        frame = tk.Frame(parent, bg=WHITE, highlightbackground=LINE, highlightthickness=1, **kwargs)
        return frame

    def _build_dashboard(self) -> None:
        self._page_heading("Oversikt", "Skriv i ditt tempo. Finn det rette ordet når du trenger det.")

        hero = tk.Frame(self._page, bg=NAVY)
        hero.pack(fill="x", pady=(0, 16))
        hero.grid_columnconfigure(0, weight=1)
        hero_left = tk.Frame(hero, bg=NAVY)
        hero_left.grid(row=0, column=0, sticky="w", padx=24, pady=19)
        tk.Label(hero_left, text="SKRIVEHJELP FOR WINDOWS  ·  BOKMÅL",
                 bg=NAVY, fg="#B7C6F9", font=("Segoe UI Semibold", 8)).pack(anchor="w")
        tk.Label(hero_left, text="Skriv det du mener.", bg=NAVY, fg=WHITE,
                 font=("Segoe UI Semibold", 22)).pack(anchor="w", pady=(7, 1))
        tk.Label(hero_left, text="Forslagene følger deg fra app til app.",
                 bg=NAVY, fg="#CBD3E4", font=("Segoe UI", 10)).pack(anchor="w")
        toggle = tk.Frame(hero, bg=NAVY)
        toggle.grid(row=0, column=1, sticky="e", padx=22)
        self.start_button = tk.Button(toggle, text="Slå på skrivehjelp", command=self.toggle_live,
                                      bd=0, padx=15, pady=10, cursor="hand2",
                                      font=("Segoe UI Semibold", 9))
        self.start_button.pack(anchor="e")
        tk.Label(toggle, text="F1–F5 velger ord  ·  F6 diktering  ·  F7 lukker diktering\n"
                              "F8 av  ·  F9 leser opp  ·  F10 pause  ·  F11 på  ·  F12 språk", justify="right",
                 bg=NAVY, fg="#BFC9DE", font=("Segoe UI", 8)).pack(anchor="e", pady=(8, 0))

        row = tk.Frame(self._page, bg=BG)
        row.pack(fill="x", pady=(0, 15))
        row.grid_columnconfigure(0, weight=3)
        row.grid_columnconfigure(1, weight=2)

        demo = self._card(row)
        demo.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(demo, text="Prøv et ord", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(demo, text="Skriv en feilstaving, for eksempel «skever».",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))
        entry_row = tk.Frame(demo, bg=WHITE)
        entry_row.pack(fill="x", padx=18)
        self.demo_var = tk.StringVar()
        self.demo_entry = ttk.Entry(entry_row, textvariable=self.demo_var, font=("Segoe UI", 11))
        self.demo_entry.pack(side="left", fill="x", expand=True)
        self.demo_entry.bind("<KeyRelease>", self._update_demo)
        self.demo_entry.bind("<Return>", self._use_demo_first)
        self.demo_result = tk.Label(demo, text="Forslagene dine vises her.",
                                    bg=WHITE, fg=MUTED, font=("Segoe UI", 9))
        self.demo_result.pack(anchor="w", padx=18, pady=(10, 2))
        self.demo_suggestion_row = tk.Frame(demo, bg=WHITE)
        self.demo_suggestion_row.pack(fill="x", padx=14, pady=(0, 15))

        tools = self._card(row)
        tools.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(tools, text="Hurtigverktøy", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18, pady=(16, 11))
        self._tool_row(tools, "▶", "Les tekst høyt", "Marker tekst hvor som helst og trykk F9.",
                       "Les fra tekst", self.read_demo_text)
        self._tool_row(tools, "🎙", "Diktering", "Trykk F6 og snakk. F6 igjen stopper.",
                       "Start diktering", self.launch_dictation)
        self._tool_row(tools, "Aa", "Mine ord", "Lær ord du ofte bruker.",
                       "Åpne ordliste", lambda: self.show_page("Mine ord"))

        text_card = self._card(self._page)
        text_card.pack(fill="both", expand=True)
        text_header = tk.Frame(text_card, bg=WHITE)
        text_header.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(text_header, text="Tekstkontroll", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(side="left")
        ttk.Button(text_header, text="Kontroller tekst", command=self.check_text,
                   style="Primary.TButton").pack(side="right")
        ttk.Button(text_header, text="Les teksten", command=self.read_demo_text,
                   style="Soft.TButton").pack(side="right", padx=(0, 8))
        tk.Label(text_card, text="Lim inn eller skriv tekst. Ukjente ord får forslag som du kan sette inn.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        self.text_box = tk.Text(text_card, height=5, wrap="word", bd=0, relief="flat",
                                font=("Segoe UI", 10), fg=INK, insertbackground=BLUE,
                                padx=12, pady=10, highlightthickness=1,
                                highlightbackground=LINE, highlightcolor=BLUE)
        self.text_box.pack(fill="x", padx=18, pady=(8, 8))
        self.check_results = tk.Frame(text_card, bg=WHITE)
        self.check_results.pack(fill="x", padx=18, pady=(0, 12))

    def _tool_row(self, parent: tk.Widget, icon: str, title: str, detail: str,
                  action: str, command) -> None:
        row = tk.Frame(parent, bg=WHITE)
        row.pack(fill="x", padx=16, pady=3)
        badge = tk.Label(row, text=icon, width=3, bg="#F0F2FE", fg=PURPLE,
                         font=("Segoe UI Semibold", 10), pady=8)
        badge.pack(side="left", padx=(0, 9))
        body = tk.Frame(row, bg=WHITE)
        body.pack(side="left", fill="x", expand=True)
        tk.Label(body, text=title, bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")
        tk.Label(body, text=detail, bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))
        tk.Button(row, text=action, command=command, bd=0, bg="#F5F7FC", fg=BLUE,
                  cursor="hand2", padx=9, pady=7, font=("Segoe UI Semibold", 8),
                  activebackground="#E9EDFA").pack(side="right")

    def _build_my_words(self) -> None:
        self._page_heading("Mine ord", "Legg til ord og rettinger som skal være riktige for deg.")
        card = self._card(self._page)
        card.pack(fill="x", pady=(0, 14))
        tk.Label(card, text="Legg til et ord", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(card, text="Navn, fagord og andre ord du skriver ofte, blir aldri foreslått rettet.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        word_row = tk.Frame(card, bg=WHITE)
        word_row.pack(fill="x", padx=20, pady=(12, 18))
        self.word_var = tk.StringVar()
        word_entry = ttk.Entry(word_row, textvariable=self.word_var, font=("Segoe UI", 10))
        word_entry.pack(side="left", fill="x", expand=True)
        word_entry.bind("<Return>", lambda _e: self.add_word())
        ttk.Button(word_row, text="Legg til ord", command=self.add_word,
                   style="Primary.TButton").pack(side="left", padx=(8, 0))

        learn = self._card(self._page)
        learn.pack(fill="x", pady=(0, 14))
        tk.Label(learn, text="Lær en egen retting", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(learn, text="For eksempel: «skever» → «skriver». Den lagres bare på denne PC-en.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        pair_row = tk.Frame(learn, bg=WHITE)
        pair_row.pack(fill="x", padx=20, pady=(12, 18))
        self.typo_var = tk.StringVar()
        self.fix_var = tk.StringVar()
        ttk.Entry(pair_row, textvariable=self.typo_var).pack(side="left", fill="x", expand=True)
        tk.Label(pair_row, text="→", bg=WHITE, fg=MUTED,
                 font=("Segoe UI Semibold", 14)).pack(side="left", padx=10)
        ttk.Entry(pair_row, textvariable=self.fix_var).pack(side="left", fill="x", expand=True)
        ttk.Button(pair_row, text="Lagre retting", command=self.add_correction,
                   style="Primary.TButton").pack(side="left", padx=(8, 0))

        self.word_count_label = tk.Label(self._page, text="", bg=BG, fg=MUTED,
                                         font=("Segoe UI Semibold", 10))
        self.word_count_label.pack(anchor="w", pady=(4, 8))
        self.word_list = tk.Frame(self._page, bg=BG)
        self.word_list.pack(fill="both", expand=True)
        self._refresh_word_list()

    def _build_settings(self) -> None:
        self._page_heading("Innstillinger", "Tilpass hvordan skrivehjelpen oppfører seg.")
        live = self._card(self._page)
        live.pack(fill="x", pady=(0, 14))
        tk.Label(live, text="Skrivehjelp i andre apper", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(live, text="Når dette er på, følger forslagene deg i nettleser, Word og andre skrivefelt.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        self.settings_toggle = ttk.Button(live, text="Slå på skrivehjelp", command=self.toggle_live,
                                          style="Primary.TButton")
        self.settings_toggle.pack(anchor="w", padx=20, pady=(13, 19))

        how = self._card(self._page)
        how.pack(fill="x", pady=(0, 14))
        tk.Label(how, text="Slik velger du et forslag", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(how, text="1. Skriv som vanlig i et annet program.\n"
                           "2. Når forslagsvinduet vises, trykk F1 for ord 1, F2 for ord 2, osv. (opp til F5).\n"
                           "3. Ordet byttes ut og rettingen huskes lokalt.\n"
                           "Trykk Esc for å lukke forslagene.\n\n"
                           "Les opp tekst: marker tekst i et hvilket som helst program og trykk F9.\n"
                           "Trykk F10 for pause, og F10 igjen for å fortsette. F9 igjen stopper.\n\n"
                           "F8 slår av Skriveflyt og skjuler vinduet. F11 slår den på igjen.\n\n"
                           "Diktering: trykk F6 der du skriver, og snakk. Teksten skrives for deg.\n"
                           "Trykk F6 igjen for å stoppe. Trykk F7 for å lukke dikteringsvinduet.",
                 bg=WHITE, fg=MUTED, justify="left", font=("Segoe UI", 10)
                 ).pack(anchor="w", padx=20, pady=(5, 18))

        lang_card = self._card(self._page)
        lang_card.pack(fill="x", pady=(0, 14))
        tk.Label(lang_card, text="Språk", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(lang_card, text="F12 bytter mellom norsk og engelsk: ordforslag, diktering og opplesing.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        self.language_button = ttk.Button(lang_card, command=self.toggle_language, style="Primary.TButton")
        self.language_button.pack(anchor="w", padx=20, pady=(13, 19))
        self._update_language_button()

        auto = self._card(self._page)
        auto.pack(fill="x", pady=(0, 14))
        tk.Label(auto, text="Start når PC-en starter", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(auto, text="Skriveflyt starter av seg selv når du logger på, uten svart vindu.",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        self.autostart_button = ttk.Button(auto, command=self.toggle_autostart, style="Primary.TButton")
        self.autostart_button.pack(anchor="w", padx=20, pady=(13, 19))
        self._update_autostart_button()

        info = self._card(self._page)
        info.pack(fill="x")
        tk.Label(info, text="Om denne versjonen", bg=WHITE, fg=INK,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=20, pady=(18, 5))
        tk.Label(info, text="Skriveflyt er en lokal prototype med norske ordmønstre, personlige rettinger, "
                            "tekstkontroll, opplesing og Windows-diktering. Ordlisten er en startliste og "
                            "blir bedre når du lærer den ordene dine.",
                 bg=WHITE, fg=MUTED, wraplength=690, justify="left",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 18))

    def _update_status(self) -> None:
        if not hasattr(self, "status_pill"):
            return
        language = "Norsk" if self.engine.language == "nb" else "Engelsk"
        if self.live_active and self.assistant.sleeping:
            self.status_pill.configure(text="●  Av  ·  F11 slår på", bg="#EDF0F5", fg=MUTED)
        elif self.live_active:
            self.status_pill.configure(text=f"●  Aktiv  ·  {language}", bg=MINT, fg=GREEN)
        else:
            self.status_pill.configure(text="●  Av", bg="#EDF0F5", fg=MUTED)
        if self.start_button is not None and self.start_button.winfo_exists():
            self.start_button.configure(text="Slå av skrivehjelp" if self.live_active else "Slå på skrivehjelp",
                                        bg="#E6F6F0" if self.live_active else "#7385F2",
                                        fg=GREEN if self.live_active else WHITE,
                                        activebackground="#D4EFE4" if self.live_active else "#6375E5")
        if self.settings_toggle is not None and self.settings_toggle.winfo_exists():
            self.settings_toggle.configure(text="Slå av skrivehjelp" if self.live_active else "Slå på skrivehjelp")

    def start_live(self) -> None:
        if self.live_active:
            return
        try:
            self.assistant.start()
            self.live_active = True
            self._update_status()
            self.root.after(350, self._check_live_started)
        except OSError as error:
            messagebox.showerror("Kunne ikke starte", str(error), parent=self.root)

    def _check_live_started(self) -> None:
        if self.live_active and not self.assistant.enabled:
            self.live_active = False
            self._update_status()
            messagebox.showerror(
                "Kunne ikke starte skrivehjelpen",
                "Windows kunne ikke starte tastaturhjelpen. Kontroller at appen har tilgang til å kjøre i bakgrunnen.",
                parent=self.root,
            )

    def toggle_live(self) -> None:
        if self.live_active:
            self.assistant.stop()
            self.live_active = False
            self._hide_live_overlay()
            self._update_status()
        else:
            self.start_live()

    # These three are called from the keyboard thread: only queue work here.
    def _queue_suggestions(self, typed: str, _suggestions: list[str], target: int) -> None:
        self._ui_queue.put((self._show_live_suggestions, (typed, target)))

    def _queue_hide(self) -> None:
        self._ui_queue.put((self._hide_live_overlay, ()))

    def _queue_learned(self, typo: str, replacement: str) -> None:
        self._ui_queue.put((self._show_learned, (typo, replacement)))

    def _queue_sleep(self) -> None:
        self._ui_queue.put((self.sleep_app, ()))

    def _queue_wake(self) -> None:
        self._ui_queue.put((self.wake_app, ()))

    def sleep_app(self) -> None:
        """F8: hide Skriveflyt and turn all help off until F11."""
        self.stop_speaking()
        self._hide_live_overlay()
        self.root.withdraw()
        self._update_status()
        self._show_toast("Skriveflyt er av", "Trykk F11 for å slå den på igjen")

    def wake_app(self) -> None:
        """F11: show Skriveflyt again and turn the help on."""
        if not self.live_active:
            self.start_live()
        self.root.deiconify()
        self.root.lift()
        self._update_status()
        self._show_toast("Skriveflyt er på", "F8 slår den av")

    def _queue_pause(self) -> None:
        self._ui_queue.put((self.pause_speaking, ()))

    def _queue_toggle_language(self) -> None:
        self._ui_queue.put((self.toggle_language, ()))

    def _queue_dictate(self) -> None:
        # Win+H is pressed by the keyboard thread; nothing else to do in the UI.
        pass

    def _queue_read_selection(self) -> None:
        self._ui_queue.put((self.read_selection, ()))

    def _drain_ui_queue(self) -> None:
        latest_suggestion = None
        jobs = []
        try:
            while True:
                fn, args = self._ui_queue.get_nowait()
                if fn == self._show_live_suggestions:
                    latest_suggestion = len(jobs)
                jobs.append((fn, args))
        except queue.Empty:
            pass
        for index, (fn, args) in enumerate(jobs):
            # Only the newest word needs suggestions when typing fast.
            if fn == self._show_live_suggestions and index != latest_suggestion:
                continue
            try:
                fn(*args)
            except Exception as error:
                log(f"UI FEIL i {getattr(fn, '__name__', fn)}: {error!r}")
        try:
            self.root.after(30, self._drain_ui_queue)
        except tk.TclError:
            pass

    def _show_live_suggestions(self, typed: str, target: int) -> None:
        if not self.live_active:
            return
        choices = self.engine.suggestions(typed)
        self.assistant.set_suggestions(typed, choices, target)
        if choices:
            self._show_live_overlay(typed, choices)
        else:
            self._hide_live_overlay()

    def _create_live_overlay(self) -> None:
        """Create the suggestion popup once, while Skriveflyt itself has focus.

        The popup gets WS_EX_NOACTIVATE on its real (outer) window, so showing
        it or clicking it never takes focus from Word, the browser, etc.
        Earlier the style was set on the inner Tk window, so the popup stole
        focus and F1-F5 went nowhere.
        """
        if self.live_overlay is not None and self.live_overlay.winfo_exists():
            return
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=WHITE, highlightbackground=LINE, highlightthickness=1)
        popup.geometry("1x1+-4000+-4000")
        self.live_overlay = popup
        if os.name != "nt":
            popup.withdraw()
            return
        popup.update()
        try:
            hwnd = int(popup.wm_frame(), 16)
        except (tk.TclError, ValueError):
            hwnd = 0
        if not hwnd:
            hwnd = popup.winfo_id()
        self.live_overlay_hwnd = hwnd
        self.assistant.overlay_hwnd = hwnd
        log(f"popup laget: hwnd={hwnd} winfo_id={popup.winfo_id()}")
        self._make_overlay_no_activate(hwnd)
        self._win_show(hwnd, False)
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _show_live_overlay(self, typed: str, choices: list[str]) -> None:
        log(f"viser popup for {typed!r}")
        if self.live_overlay is None or not self.live_overlay.winfo_exists():
            self._create_live_overlay()
        popup = self.live_overlay
        for child in popup.winfo_children():
            child.destroy()
        language = "NORSK" if self.engine.language == "nb" else "ENGELSK"
        tk.Label(popup, text=f"FORSLAG TIL  «{typed}»  ·  {language}", bg=WHITE, fg=MUTED,
                 font=("Segoe UI Semibold", 8), anchor="w").pack(fill="x", padx=14, pady=(11, 5))
        for index, word in enumerate(choices[:5], 1):
            row = tk.Frame(popup, bg=WHITE)
            row.pack(fill="x", padx=9, pady=1)
            number = tk.Label(row, text=str(index), width=2, bg="#EEF0FF", fg=PURPLE,
                              font=("Segoe UI Semibold", 9), pady=5, cursor="hand2")
            number.pack(side="left")
            word_label = tk.Label(row, text=word, bg=WHITE, fg=INK,
                                  font=("Segoe UI Semibold", 10), anchor="w", cursor="hand2")
            word_label.pack(side="left", padx=9, fill="x", expand=True)
            hint = tk.Label(row, text=f"F{index}", bg="#F4F6FA", fg=INK,
                            font=("Segoe UI Semibold", 9), padx=6, cursor="hand2")
            hint.pack(side="right", padx=(0, 6))
            for item in (row, number, word_label, hint):
                item.bind("<Button-1>", lambda _event, picked=index - 1:
                          self._select_live_suggestion(picked))
        tk.Label(popup, text="Trykk F1 for ord 1, F2 for ord 2 …  ·  Esc lukker",
                 bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=14, pady=(5, 10))
        popup.update_idletasks()
        width = max(260, popup.winfo_reqwidth())
        height = popup.winfo_reqheight()
        x = max(12, self.root.winfo_screenwidth() - width - 24)
        y = max(12, self.root.winfo_screenheight() - height - 72)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.update_idletasks()
        if os.name == "nt" and self.live_overlay_hwnd:
            self._win_place(self.live_overlay_hwnd, x, y, width, height)
        else:
            popup.deiconify()
        self.root.after(8000, lambda word=typed: self._expire_live_overlay(word))

    def _expire_live_overlay(self, typed: str) -> None:
        if self.assistant._buffer.casefold() == typed.casefold():
            self._hide_live_overlay()

    def _select_live_suggestion(self, index: int) -> None:
        self.assistant.select_by_click(index)

    @staticmethod
    def _user32():
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        return user32

    @classmethod
    def _make_overlay_no_activate(cls, hwnd: int) -> None:
        if os.name != "nt" or not hwnd:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = cls._user32()
            get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            set_style = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t
            style = get_style(hwnd, -20)  # GWL_EXSTYLE
            # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            set_style(hwnd, -20, style | 0x08000000 | 0x00000080 | 0x00000008)
        except Exception:
            pass

    @classmethod
    def _win_show(cls, hwnd: int, visible: bool) -> None:
        try:
            # SW_SHOWNOACTIVATE = 4, SW_HIDE = 0
            cls._user32().ShowWindow(hwnd, 4 if visible else 0)
        except Exception:
            pass

    @classmethod
    def _win_place(cls, hwnd: int, x: int, y: int, width: int, height: int) -> None:
        try:
            import ctypes
            # HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW
            cls._user32().SetWindowPos(hwnd, ctypes.c_void_p(-1), x, y, width, height,
                                       0x0010 | 0x0040)
        except Exception:
            pass

    def _hide_live_overlay(self) -> None:
        if self.live_overlay is None:
            return
        try:
            if os.name == "nt" and self.live_overlay_hwnd:
                self._win_show(self.live_overlay_hwnd, False)
            else:
                self.live_overlay.withdraw()
        except tk.TclError:
            self.live_overlay = None
            self.live_overlay_hwnd = 0
            self.assistant.overlay_hwnd = 0

    def _show_learned(self, typo: str, replacement: str) -> None:
        if self.active_page == "Oversikt":
            self.demo_result.configure(text=f"Rettet «{typo}» til «{replacement}» — dette huskes.",
                                       fg=GREEN)
        if self.active_page == "Mine ord":
            self._refresh_word_list()

    def _update_demo(self, _event=None) -> None:
        typed = self.demo_var.get().strip()
        self._demo_suggestions = []
        for child in self.demo_suggestion_row.winfo_children():
            child.destroy()
        if len(typed) < 2:
            self.demo_result.configure(text="Forslagene dine vises her.", fg=MUTED)
            return
        choices = self.engine.suggestions(typed)
        self._demo_suggestions = choices
        if not choices:
            self.demo_result.configure(text="Ingen forslag akkurat nå. Du kan lære appen en egen retting.",
                                       fg=MUTED)
            return
        self.demo_result.configure(text="Trykk på et forslag:", fg=MUTED)
        for index, word in enumerate(choices[:5], 1):
            tk.Button(self.demo_suggestion_row, text=f"{index}   {word}",
                      command=lambda picked=word: self._select_demo(picked),
                      bd=0, bg="#EEF0FF", fg=PURPLE, activebackground="#E2E6FF",
                      padx=10, pady=7, cursor="hand2",
                      font=("Segoe UI Semibold", 9)).pack(side="left", padx=4, pady=5)

    def _select_demo(self, word: str) -> None:
        typed = self.demo_var.get().strip()
        self.engine.learn(typed, word)
        self.demo_var.set(word)
        self.demo_entry.icursor(tk.END)
        self.demo_result.configure(text=f"Rettet «{typed}» til «{word}» — dette huskes.",
                                   fg=GREEN)
        self._update_demo()

    def _use_demo_first(self, _event=None) -> str:
        if self._demo_suggestions:
            self._select_demo(self._demo_suggestions[0])
        return "break"

    def check_text(self) -> None:
        for child in self.check_results.winfo_children():
            child.destroy()
        text = self.text_box.get("1.0", "end-1c")
        errors = self.engine.check_text(text)
        if not errors:
            tk.Label(self.check_results, text="Kontrollen er ferdig. Fant ingen ord med sikre forslag.",
                     bg=WHITE, fg=GREEN, font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 8))
            return
        tk.Label(self.check_results, text=f"Fant {len(errors)} ord med forslag:",
                 bg=WHITE, fg=INK, font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 4))
        for token, choices in errors[:8]:
            row = tk.Frame(self.check_results, bg=WHITE)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=token, bg="#FFF5E8", fg="#966010",
                     font=("Segoe UI Semibold", 9), padx=7, pady=4).pack(side="left")
            for fix in choices[:3]:
                tk.Button(row, text=fix, command=lambda old=token, new=fix: self._replace_in_text(old, new),
                          bd=0, bg="#EEF0FF", fg=PURPLE, cursor="hand2", padx=8, pady=4,
                          font=("Segoe UI Semibold", 8)).pack(side="left", padx=(6, 0))

    def _replace_in_text(self, old: str, new: str) -> None:
        content = self.text_box.get("1.0", "end-1c")
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", content.replace(old, new))
        self.engine.learn(old, new)
        self.check_text()

    def add_word(self) -> None:
        word = self.word_var.get().strip()
        if not word:
            return
        self.engine.add_word(word)
        self.word_var.set("")
        self._refresh_word_list()

    def add_correction(self) -> None:
        typo, fix = self.typo_var.get().strip(), self.fix_var.get().strip()
        if not typo or not fix:
            messagebox.showinfo("Fyll inn begge ordene", "Skriv inn feilstavingen og riktig ord.", parent=self.root)
            return
        self.engine.learn(typo, fix)
        self.typo_var.set("")
        self.fix_var.set("")
        self._refresh_word_list()

    def _refresh_word_list(self) -> None:
        if not hasattr(self, "word_list") or not self.word_list.winfo_exists():
            return
        for child in self.word_list.winfo_children():
            child.destroy()
        words = sorted(self.engine.personal_words)
        self.word_count_label.configure(text=f"Personlige ord: {len(words)}")
        visible = words[-120:]
        for start in range(0, len(visible), 4):
            row = tk.Frame(self.word_list, bg=BG)
            row.pack(fill="x", pady=3)
            for word in visible[start:start + 4]:
                tag = tk.Label(row, text=word, bg=WHITE, fg=INK, padx=10, pady=7,
                               font=("Segoe UI", 9), highlightbackground=LINE, highlightthickness=1)
                tag.pack(side="left", padx=(0, 7))

    def read_demo_text(self) -> None:
        text = ""
        if hasattr(self, "text_box") and self.text_box.winfo_exists():
            text = self.text_box.get("1.0", "end-1c").strip()
        if not text and hasattr(self, "demo_var"):
            text = self.demo_var.get().strip()
        if not text:
            text = simpledialog.askstring("Les tekst høyt", "Skriv inn teksten du vil høre:",
                                          parent=self.root) or ""
        if not text:
            return
        if os.name != "nt":
            messagebox.showinfo("Opplesing", "Opplesing bruker Windows sin innebygde tale.", parent=self.root)
            return
        self._speak(text)

    # ---------- Opplesing ----------

    @staticmethod
    def _clipboard_sequence() -> int:
        if os.name != "nt":
            return 0
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32")
            user32.GetClipboardSequenceNumber.restype = ctypes.c_ulong
            return int(user32.GetClipboardSequenceNumber())
        except Exception:
            return 0

    def pause_speaking(self) -> None:
        """F10: pause the reading, F10 again continues where it stopped."""
        proc = self._speech_proc
        if proc is None or proc.poll() is not None or os.name != "nt":
            self._speech_paused = False
            return
        try:
            import ctypes
            ntdll = ctypes.WinDLL("ntdll")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
            ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
            handle = kernel32.OpenProcess(0x0800, False, proc.pid)  # PROCESS_SUSPEND_RESUME
            if not handle:
                log(f"pause FEIL: fikk ikke tilgang ({ctypes.get_last_error()})")
                return
            try:
                if self._speech_paused:
                    ntdll.NtResumeProcess(handle)
                    self._speech_paused = False
                    log("opplesing fortsetter")
                    self._show_toast("Fortsetter", "F10 setter på pause")
                else:
                    ntdll.NtSuspendProcess(handle)
                    self._speech_paused = True
                    log("opplesing på pause")
                    self._show_toast("Pause", "F10 fortsetter  ·  F9 stopper")
            finally:
                kernel32.CloseHandle(handle)
        except Exception as error:
            log(f"pause FEIL: {error!r}")

    def stop_speaking(self) -> bool:
        proc = self._speech_proc
        self._speech_proc = None
        self._speech_paused = False
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
            return True
        return False

    def read_selection(self) -> None:
        """F9: copy the marked text in the active app and read it aloud."""
        if self.stop_speaking():
            log("opplesing stoppet")
            return
        before = self._clipboard_sequence()
        try:
            old_text = self.root.clipboard_get()
        except tk.TclError:
            old_text = None
        self.assistant.send_copy()
        self.root.after(150, self._finish_read_selection, before, old_text, 0)

    def _finish_read_selection(self, before: int, old_text: str | None, tries: int) -> None:
        if self._clipboard_sequence() == before:
            if tries < 6:
                self.root.after(100, self._finish_read_selection, before, old_text, tries + 1)
            else:
                log("F9: fant ingen markert tekst")
            return
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        # Put back what was on the clipboard before (if it was text).
        if old_text is not None:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(old_text)
            except tk.TclError:
                pass
        text = text.strip()
        log(f"F9: leser opp {len(text)} tegn")
        if text:
            self._speak(text)

    def _speak(self, text: str) -> None:
        self.stop_speaking()
        if os.name != "nt":
            return
        try:
            handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
            with handle:
                handle.write(text)
        except OSError:
            return
        # les_opp.ps1 picks a Norwegian voice if Windows has one.
        from windows_input import LOG_FILE
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "les_opp.ps1")
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", script,
            "-TextFile", handle.name, "-LogFile", str(LOG_FILE),
            "-Language", self.engine.language,
        ]
        try:
            self._speech_proc = subprocess.Popen(
                command,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            log(f"opplesing FEIL: {error!r}")

    def launch_dictation(self) -> None:
        if os.name != "nt":
            return
        try:
            user32 = ctypes_win32()
            target = self.assistant._target_hwnd
            if target:
                user32.SetForegroundWindow.argtypes = [__import__("ctypes").c_void_p]
                user32.SetForegroundWindow(target)
            self.root.after(150, self.assistant.press_win_h)
        except Exception:
            pass

    # ---------- Språk ----------

    def toggle_language(self) -> None:
        language = self.engine.toggle_language()
        name = "Norsk" if language == "nb" else "Engelsk"
        log(f"språk byttet til {name}")
        self.assistant.switch_input_language(language)
        self._update_status()
        self._update_language_button()
        self._show_toast(f"Språk: {name}", "Ordforslag, diktering (F6) og opplesing (F9)")

    def _update_language_button(self) -> None:
        button = getattr(self, "language_button", None)
        if button is not None and button.winfo_exists():
            current = "Norsk" if self.engine.language == "nb" else "Engelsk"
            other = "engelsk" if self.engine.language == "nb" else "norsk"
            button.configure(text=f"Nå: {current}  —  bytt til {other} (F12)")

    def _show_toast(self, title: str, detail: str) -> None:
        if self.live_overlay is None or not self.live_overlay.winfo_exists():
            self._create_live_overlay()
        popup = self.live_overlay
        for child in popup.winfo_children():
            child.destroy()
        tk.Label(popup, text=title, bg=WHITE, fg=PURPLE,
                 font=("Segoe UI Semibold", 14), anchor="w").pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(popup, text=detail, bg=WHITE, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=16, pady=(0, 12))
        popup.update_idletasks()
        width = max(260, popup.winfo_reqwidth())
        height = popup.winfo_reqheight()
        x = max(12, self.root.winfo_screenwidth() - width - 24)
        y = max(12, self.root.winfo_screenheight() - height - 72)
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.update_idletasks()
        if os.name == "nt" and self.live_overlay_hwnd:
            self._win_place(self.live_overlay_hwnd, x, y, width, height)
        else:
            popup.deiconify()
        self._toast_id += 1
        toast = self._toast_id
        self.root.after(2000, lambda: self._toast_id == toast and self._hide_live_overlay())

    # ---------- Autostart ----------

    @staticmethod
    def _autostart_command() -> str:
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        python = sys.executable
        windowless = os.path.join(os.path.dirname(python), "pythonw.exe")
        if os.path.exists(windowless):
            python = windowless
        return f'"{python}" "{main_py}" --bakgrunn'

    @staticmethod
    def autostart_enabled() -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
                winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
        except OSError:
            return False

    def set_autostart(self, enabled: bool) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, self._autostart_command())
                else:
                    try:
                        winreg.DeleteValue(key, AUTOSTART_NAME)
                    except FileNotFoundError:
                        pass
            log(f"autostart {'på' if enabled else 'av'}: {self._autostart_command()}")
            return True
        except OSError as error:
            log(f"autostart FEIL: {error!r}")
            return False

    def _first_run_autostart(self) -> None:
        # Turn autostart on the first time; after that the user decides in Innstillinger.
        flag = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "autostart-valgt.txt")
        if os.path.exists(flag):
            if self.autostart_enabled():
                self.set_autostart(True)  # keep the path up to date
            return
        if self.set_autostart(True):
            try:
                os.makedirs(os.path.dirname(flag), exist_ok=True)
                with open(flag, "w", encoding="utf-8") as handle:
                    handle.write("Autostart ble slått på automatisk første gang.\n")
            except OSError:
                pass
        self._update_autostart_button()

    def toggle_autostart(self) -> None:
        self.set_autostart(not self.autostart_enabled())
        self._update_autostart_button()

    def _update_autostart_button(self) -> None:
        button = getattr(self, "autostart_button", None)
        if button is not None and button.winfo_exists():
            button.configure(text="Slå av autostart" if self.autostart_enabled() else "Slå på autostart")

    def close(self) -> None:
        self.stop_speaking()
        try:
            self.assistant.stop()
        except Exception:
            pass
        self.root.destroy()


AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "Skriveflyt"


def ctypes_win32():
    import ctypes
    return ctypes.WinDLL("user32", use_last_error=True)


def _already_running() -> bool:
    """Only one Skriveflyt at a time (two would fix every word twice)."""
    if os.name != "nt":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    global _INSTANCE_MUTEX
    _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "Local\\SkriveflytEnInstans")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


_INSTANCE_MUTEX = None


def main() -> None:
    if _already_running():
        log("Skriveflyt kjører allerede - starter ikke en ny")
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Skriveflyt kjører allerede",
                            "Skriveflyt er allerede åpen. Lukk den først hvis du vil starte på nytt.")
        root.destroy()
        return
    started_by = "Windows-oppstart" if "--bakgrunn" in sys.argv else "manuelt"
    log(f"===== Skriveflyt startet ({started_by}) =====")
    root = tk.Tk()
    SkriveflytApp(root)
    # Started with Windows (--bakgrunn): show the window so the user sees it is running.
    root.mainloop()


if __name__ == "__main__":
    main()

