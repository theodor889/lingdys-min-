"""Small Win32 low-level keyboard hook for live suggestions in other apps."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from typing import Callable


ULONG_PTR = ctypes.c_size_t

from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "skriveflyt-logg.txt"


def log(message: str) -> None:
    """Write one line to data/skriveflyt-logg.txt (for finding errors)."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%H:%M:%S')}  {message}\n")
    except Exception:
        pass


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    # Windows needs the full union (mouse is the biggest). With only the
    # keyboard part, INPUT was too small and SendInput refused every key.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class WindowsTypingAssistant:
    """Capture the current word only; offer replacements without auto-changing it."""

    def __init__(
        self,
        on_suggestions: Callable[[str, list[str], int], None],
        on_hide: Callable[[], None],
        on_learned: Callable[[str, str], None],
        on_read_selection: Callable[[], None] | None = None,
        on_dictate: Callable[[], None] | None = None,
        on_toggle_language: Callable[[], None] | None = None,
        on_pause: Callable[[], None] | None = None,
        on_sleep: Callable[[], None] | None = None,
        on_wake: Callable[[], None] | None = None,
    ) -> None:
        self.on_pause = on_pause
        self.on_sleep = on_sleep
        self.on_wake = on_wake
        # F11 puts Skriveflyt to sleep (nothing happens) until F12 wakes it.
        self.sleeping = False
        self.on_dictate = on_dictate
        self.on_toggle_language = on_toggle_language
        self._loaded_english_hkl = 0
        self.on_suggestions = on_suggestions
        self.on_hide = on_hide
        self.on_learned = on_learned
        self.on_read_selection = on_read_selection
        self.enabled = False
        self._buffer = ""
        self._target_hwnd = 0
        self._choices: list[str] = []
        self._choice_until = 0.0
        self._last_typing_at = 0.0
        self._hook = None
        self._thread_id = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._callback = None
        self._own_pid = os.getpid()
        # Window handle of the suggestion popup (set by the UI). If Windows ever
        # gives that popup focus, F1-F5 must still work for the text app.
        self.overlay_hwnd = 0
        # F-key whose key-up must also be hidden from the text app.
        self._swallow_up_vk = 0

    @staticmethod
    def _api():
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.ToUnicodeEx.argtypes = [
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
            ctypes.POINTER(wintypes.WCHAR), ctypes.c_int, wintypes.UINT, wintypes.HKL,
        ]
        user32.ToUnicodeEx.restype = ctypes.c_int
        user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
        user32.GetKeyboardState.restype = wintypes.BOOL
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        user32.GetKeyboardLayout.restype = wintypes.HKL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        return user32

    def start(self) -> None:
        if os.name != "nt":
            raise OSError("Live typing works on Windows.")
        if self.enabled:
            return
        self.enabled = True
        self._thread = threading.Thread(target=self._hook_loop, name="Skriveflyt-keyboard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.enabled = False
        user32 = self._api()
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        self._buffer = ""
        self._choices = []
        self._post(self.on_hide)

    def _post(self, fn: Callable, *args) -> None:
        # Callbacks are wired to Tk's root.after by the UI.
        try:
            fn(*args)
        except Exception:
            pass

    def _hook_loop(self) -> None:
        try:
            user32 = self._api()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            self._thread_id = kernel32.GetCurrentThreadId()

            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            def handle(code, wparam, lparam):
                if code == 0:
                    event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if not (event.flags & 0x10):  # Ignore injected keys sent by this app.
                        if wparam in (0x0100, 0x0104):  # WM_KEYDOWN / WM_SYSKEYDOWN
                            try:
                                consumed = self._handle_key(user32, event)
                            except Exception:
                                consumed = False
                            if consumed:
                                return 1
                        elif wparam in (0x0101, 0x0105):  # WM_KEYUP / WM_SYSKEYUP
                            if self._swallow_up_vk and int(event.vkCode) == self._swallow_up_vk:
                                self._swallow_up_vk = 0
                                return 1
                return user32.CallNextHookEx(self._hook, code, wparam, lparam)

            self._callback = HOOKPROC(handle)
            self._hook = user32.SetWindowsHookExW(13, self._callback, kernel32.GetModuleHandleW(None), 0)
            log(f"hook start: hook={bool(self._hook)} err={ctypes.get_last_error()}")
            if not self._hook:
                self.enabled = False
                self._post(self.on_hide)
                return
            message = MSG()
            while self.enabled and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                pass
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._thread_id = 0
            log("hook stoppet")
        except Exception as error:
            log(f"hook FEIL: {error!r}")
            self.enabled = False
            self._post(self.on_hide)

    def _foreground_is_ours(self, user32, hwnd) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self._own_pid

    def _choices_ready(self) -> bool:
        return bool(self._choices) and time.monotonic() < self._choice_until

    def _handle_key(self, user32, event: KBDLLHOOKSTRUCT) -> bool:
        vk = int(event.vkCode)
        hwnd = user32.GetForegroundWindow()
        if 0x70 <= vk <= 0x7B:
            left = self._choice_until - time.monotonic()
            log(f"F{vk - 0x6F} trykket: ord={self._buffer!r} forslag={self._choices} "
                f"tid_igjen={left:.1f}s fg={int(hwnd or 0)} mål={self._target_hwnd} "
                f"popup={self.overlay_hwnd} vår={self._foreground_is_ours(user32, hwnd) if hwnd else None}")

        # F11 = turn Skriveflyt off (sleep), F12 = turn it on again.
        if vk in (0x7A, 0x7B) and (self.on_sleep or self.on_wake):
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                self._swallow_up_vk = vk
                self._buffer = ""
                self._choices = []
                if vk == 0x7A:
                    log("F11 trykket: Skriveflyt av")
                    self.sleeping = True
                    self._post(self.on_sleep)
                else:
                    log("F12 trykket: Skriveflyt på")
                    self.sleeping = False
                    self._post(self.on_wake)
                return True
        if self.sleeping:
            return False

        # F1-F5 picks suggestion 1-5. Checked first, so it also works if the
        # popup itself happens to have focus.
        if 0x70 <= vk <= 0x74 and self._choices_ready():
            fg = int(hwnd or 0)
            if fg == self._target_hwnd or (self.overlay_hwnd and fg == self.overlay_hwnd):
                if self._choose_suggestion(vk - 0x70, user32):
                    self._swallow_up_vk = vk
                    log(f"  -> valgte forslag {vk - 0x6F}")
                    return True
                log("  -> _choose_suggestion sa nei")
            else:
                log("  -> feil vindu i fokus")

        # F6 = start/stop Windows voice typing (Win+H) where you are writing.
        if vk == 0x75 and self.on_dictate is not None:
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                log("F6 trykket: diktering")
                self._swallow_up_vk = vk
                self._buffer = ""
                self._choices = []
                self._post(self.on_hide)
                threading.Thread(target=self._press_win_h_later, daemon=True).start()
                self._post(self.on_dictate)
                return True

        # F10 = pause / continue reading aloud.
        if vk == 0x79 and self.on_pause is not None:
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                log("F10 trykket: pause/fortsett opplesing")
                self._swallow_up_vk = vk
                self._post(self.on_pause)
                return True

        # F8 = switch language (Norwegian <-> English).
        if vk == 0x77 and self.on_toggle_language is not None:
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                log("F8 trykket: bytt språk")
                self._swallow_up_vk = vk
                self._buffer = ""
                self._choices = []
                self._post(self.on_toggle_language)
                return True

        # F7 = close the Windows voice typing window.
        if vk == 0x76:
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                log("F7 trykket: lukk diktering")
                self._swallow_up_vk = vk
                threading.Thread(target=self._close_dictation_later, daemon=True).start()
                return True

        # F9 = read the marked text aloud (F9 again stops). Works in any app.
        if vk == 0x78 and self.on_read_selection is not None:
            modifier = any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x11, 0x12, 0x5B, 0x5C))
            if not modifier:
                log("F9 trykket: les opp markert tekst")
                self._swallow_up_vk = vk
                self._post(self.on_read_selection)
                return True

        if not hwnd or self._foreground_is_ours(user32, hwnd):
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
            return False

        if vk in (0x11, 0x12, 0x5B, 0x5C):  # Ctrl / Alt / Windows key
            return False
        ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
        win = bool(user32.GetAsyncKeyState(0x5B) & 0x8000) or bool(user32.GetAsyncKeyState(0x5C) & 0x8000)
        if ctrl or alt or win:
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
            return False

        if vk == 0x1B:  # Escape
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
            return False

        if (0x31 <= vk <= 0x35 and self._choices_ready()
                and time.monotonic() - self._last_typing_at > 0.3):
            index = vk - 0x31
            if self._choose_suggestion(index, user32):
                return True

        # Arrow keys, Home/End, PgUp/PgDn and Delete move away from the word.
        if 0x21 <= vk <= 0x28 or vk == 0x2E:
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
            return False

        if vk == 0x08:  # Backspace
            self._buffer = self._buffer[:-1]
            self._target_hwnd = int(hwnd)
            self._last_typing_at = time.monotonic()
            self._publish()
            return False
        if vk in (0x20, 0x0D, 0x09):  # Space, Enter, Tab
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
            return False

        char = self._to_char(user32, event, hwnd)
        if char and char.isalpha():
            if self._target_hwnd and int(hwnd) != self._target_hwnd:
                self._buffer = ""
            self._target_hwnd = int(hwnd)
            self._buffer = (self._buffer + char)[-36:]
            self._last_typing_at = time.monotonic()
            self._publish()
        elif char:
            self._buffer = ""
            self._choices = []
            self._post(self.on_hide)
        return False

    def select_by_click(self, index: int) -> bool:
        """Select a visible suggestion without moving focus away from the text app."""
        if not self.enabled:
            return False
        return self._choose_suggestion(index, self._api())

    def _choose_suggestion(self, index: int, user32) -> bool:
        if index >= len(self._choices) or time.monotonic() >= self._choice_until:
            return False
        target = self._target_hwnd
        fg = int(user32.GetForegroundWindow() or 0)
        if not target or (fg != target and not (self.overlay_hwnd and fg == self.overlay_hwnd)):
            return False
        selected = self._choices[index]
        typo = self._buffer
        if not typo:
            return False
        self._buffer = ""
        self._choices = []
        self._post(self.on_hide)
        self._post(self.on_learned, typo, selected)
        # Type the replacement after the hook has returned, so Windows has
        # finished handling the F-key before new keys are sent.
        threading.Thread(
            target=self._replace_later, args=(target, fg, typo, selected),
            name="Skriveflyt-replace", daemon=True,
        ).start()
        return True

    def _replace_later(self, target: int, fg: int, typo: str, selected: str) -> None:
        try:
            user32 = self._api()
            if fg != target:
                # The popup had focus: give it back to the text app first.
                user32.SetForegroundWindow(target)
                time.sleep(0.05)
            time.sleep(0.02)
            self._insert_replacement(user32, typo, selected)
            log(f"  -> byttet {typo!r} med {selected!r}")
        except Exception as error:
            log(f"  -> FEIL ved bytte: {error!r}")

    @staticmethod
    def _to_char(user32, event: KBDLLHOOKSTRUCT, hwnd) -> str:
        state = (ctypes.c_ubyte * 256)()
        if not user32.GetKeyboardState(state):
            return ""
        state[event.vkCode] |= 0x80
        thread = user32.GetWindowThreadProcessId(hwnd, None)
        layout = user32.GetKeyboardLayout(thread)
        chars = ctypes.create_unicode_buffer(8)
        count = user32.ToUnicodeEx(event.vkCode, event.scanCode, state, chars, 8, 0, layout)
        return chars.value[:1] if count > 0 else ""

    def _publish(self) -> None:
        if len(self._buffer) < 2:
            self._choices = []
            self._post(self.on_hide)
            return
        self._choice_until = time.monotonic() + 8
        self._post(self.on_suggestions, self._buffer, [], self._target_hwnd)

    def set_suggestions(self, typed: str, suggestions: list[str], target: int) -> None:
        # Called from the Tk thread after calculating the candidates.
        if typed.casefold() != self._buffer.casefold() or target != self._target_hwnd:
            return
        self._choices = suggestions[:5]
        self._choice_until = time.monotonic() + 8
        log(f"forslag for {typed!r}: {self._choices}")

    def _press_win_h_later(self) -> None:
        # Wait until the F6 key is released, then press Win+H.
        time.sleep(0.12)
        self.press_win_h()

    @staticmethod
    def _window_info(user32, hwnd) -> str:
        title = ctypes.create_unicode_buffer(256)
        klass = ctypes.create_unicode_buffer(256)
        try:
            user32.GetWindowTextW(hwnd, title, 256)
            user32.GetClassNameW(hwnd, klass, 256)
        except Exception:
            pass
        return f"{title.value!r} / {klass.value!r}"

    def _close_dictation_later(self) -> None:
        # Windows has no key that closes voice typing, so lukk_diktering.ps1
        # presses the window's close button with UI Automation.
        try:
            import subprocess
            script = Path(__file__).resolve().parent / "lukk_diktering.ps1"
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-WindowStyle", "Hidden", "-File", str(script), "-LogFile", str(LOG_FILE)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as error:
            log(f"  F7 FEIL: {error!r}")

    def switch_input_language(self, language: str) -> None:
        """Switch the Windows keyboard language, so voice typing (Win+H)
        listens in that language. Runs in the background."""
        threading.Thread(target=self._switch_input_language, args=(language,),
                         name="Skriveflyt-language", daemon=True).start()

    def _switch_input_language(self, language: str) -> None:
        try:
            user32 = self._api()
            user32.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(wintypes.HKL)]
            user32.GetKeyboardLayoutList.restype = ctypes.c_int
            user32.LoadKeyboardLayoutW.argtypes = [wintypes.LPCWSTR, wintypes.UINT]
            user32.LoadKeyboardLayoutW.restype = wintypes.HKL
            user32.UnloadKeyboardLayout.argtypes = [wintypes.HKL]
            user32.UnloadKeyboardLayout.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL

            count = user32.GetKeyboardLayoutList(0, None)
            layouts = (wintypes.HKL * max(count, 1))()
            count = user32.GetKeyboardLayoutList(count, layouts)
            handles = [int(layouts[i] or 0) for i in range(count)]
            log(f"tastaturspråk på PC-en: {[hex(h & 0xFFFFFFFF) for h in handles]}")

            primary = 0x09 if language == "en" else 0x14  # English / Norwegian
            matches = [h for h in handles if (h & 0x3FF) == primary]
            # For English, prefer one that keeps the Norwegian key layout (æ ø å).
            matches.sort(key=lambda h: 0 if ((h >> 16) & 0xFFFF) == 0x0414 else 1)
            target = matches[0] if matches else 0

            if not target and language == "en":
                target = int(user32.LoadKeyboardLayoutW("00000409", 0) or 0)
                self._loaded_english_hkl = target
                log("la til engelsk (US) tastatur midlertidig")
            if not target:
                log(f"fant ikke tastaturspråk for {language}")
                return

            hwnd = user32.GetForegroundWindow()
            user32.PostMessageW(hwnd, 0x0050, 0, target)  # WM_INPUTLANGCHANGEREQUEST
            log(f"byttet tastaturspråk til {language}: {hex(target & 0xFFFFFFFF)}")

            if language == "nb" and self._loaded_english_hkl:
                time.sleep(0.3)
                user32.UnloadKeyboardLayout(self._loaded_english_hkl)
                self._loaded_english_hkl = 0
        except Exception as error:
            log(f"bytte tastaturspråk FEIL: {error!r}")

    def press_win_h(self) -> None:
        """Open/close Windows voice typing in the app that has focus."""
        user32 = self._api()
        keyup = 0x0002
        self._send_keys(user32, [(0x5B, 0), (0x48, 0), (0x48, keyup), (0x5B, keyup)])

    def send_copy(self) -> None:
        """Press Ctrl+C in the app that has focus (to copy the marked text)."""
        user32 = self._api()
        keyup = 0x0002
        self._send_keys(user32, [(0x11, 0), (0x43, 0), (0x43, keyup), (0x11, keyup)])

    def _send_keys(self, user32, keys: list[tuple[int, int]]) -> None:
        inputs = (INPUT * len(keys))()
        for index, (vk, flags) in enumerate(keys):
            inputs[index].type = 1  # INPUT_KEYBOARD
            inputs[index].ki = KEYBDINPUT(vk, 0, flags, 0, 0)
        sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            log(f"  -> SendInput sendte {sent}/{len(inputs)} taster, feil={ctypes.get_last_error()}")

    def _insert_replacement(self, user32, typo: str, replacement: str) -> None:
        # Erase exactly the letters that were typed (one Backspace each), then
        # type the new word as Unicode so the user's clipboard is not touched.
        keyup = 0x0002
        backspaces: list[tuple[int, int]] = []
        for _ in typo:
            backspaces += [(0x08, 0), (0x08, keyup)]
        if backspaces:
            self._send_keys(user32, backspaces)
        for char in self._match_case(typo, replacement):
            down = INPUT(type=1, ki=KEYBDINPUT(0, ord(char), 0x0004, 0, 0))
            up = INPUT(type=1, ki=KEYBDINPUT(0, ord(char), 0x0004 | keyup, 0, 0))
            batch = (INPUT * 2)(down, up)
            sent = user32.SendInput(2, batch, ctypes.sizeof(INPUT))
            if sent != 2:
                log(f"  -> SendInput bokstav feilet, feil={ctypes.get_last_error()}")

    @staticmethod
    def _match_case(typo: str, replacement: str) -> str:
        if len(typo) > 1 and typo.isupper():
            return replacement.upper()
        if typo[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement

