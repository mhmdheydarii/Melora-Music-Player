#!/usr/bin/env python3
"""
MELORA  -  a modern dark music player
=====================================
Python + tkinter + Pillow (anti-aliased graphics) + pygame (audio)

Install :  pip install pygame mutagen pillow tkinterdnd2
Run     :  python music_player.py

Highlights
  * Animated UI: smooth scrolling, hover fades, staggered list entrance,
    colour themes that morph to the current album art, animated equalizer
  * Drag & drop a folder -> instant playlist + autoplay (with a drop overlay)
  * Real album art (ID3 / FLAC / MP4 / folder.jpg) or generated gradient covers
  * Playlists, rename / delete, shuffle, repeat, seek, volume, mute
  * Search: Ctrl+F (or click the search box) - live filter by title / artist
  Keys: Space play/pause | <- -> seek 5s | Up/Down volume | M mute
          Ctrl+<- / Ctrl+-> previous / next | Delete remove track
"""
import colorsys
import hashlib
import io
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

import pygame
from mutagen import File as MutagenFile
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ───────────────────────── theme ─────────────────────────
BG, SIDEBAR, PANEL = "#0d0d12", "#09090c", "#111117"
CARD, HOVER, SELROW, BORDER = "#17171f", "#1f1f2a", "#181823", "#1d1d27"
TEXT, SUB, DIM, TRACK = "#f5f5f9", "#a0a0b2", "#5f5f72", "#34344a"
BRAND, BRAND_HI = "#8b5cf6", "#b59cff"
PILL = "#1a1a25"

AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"}
DATA_FILE = Path.home() / ".melora_player.json"
OLD_DATA = Path.home() / ".sonara_player.json"   # migrated automatically
SB_W, BAR_H, HDR, RH = 252, 96, 280, 52
ROW0 = HDR + 46


# ───────────────────────── helpers ─────────────────────────
def h2r(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def r2h(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def mix(a, b, t):
    ra, rb = h2r(a), h2r(b)
    return r2h([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def smooth(t):
    return t * t * (3 - 2 * t)


def out_cubic(t):
    return 1 - (1 - t) ** 3


def q(v, steps=6):
    return round(v * steps) / steps


def fmt_time(s):
    s = max(0, int(s))
    return f"{s // 60}:{s % 60:02d}"


def fmt_long(s):
    m = int(s // 60)
    return f"{m // 60} hr {m % 60} min" if m >= 60 else f"{m} min"


def scan_folder(folder):
    out = []
    for r, _, files in os.walk(folder):
        for f in files:
            if Path(f).suffix.lower() in AUDIO_EXT:
                out.append(os.path.join(r, f))
    return sorted(out, key=lambda p: p.lower())


def pick_font(root):
    fams = set(tkfont.families(root))
    for f in ("Segoe UI Variable Display", "Segoe UI", "SF Pro Display", "Inter",
              "Helvetica Neue", "Ubuntu", "Noto Sans", "DejaVu Sans"):
        if f in fams:
            return f
    return "Helvetica"


def dark_titlebar(win):
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(ctypes.c_int(1)), 4)
    except Exception:
        pass


def reveal(path):
    folder = os.path.dirname(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass


def rr(c, x1, y1, x2, y2, r, **kw):
    """anti-aliased-looking rounded rectangle polygon"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    p = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r,
         x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
         x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    return c.create_polygon(p, smooth=True, **kw)


# ───────────────────────── Pillow graphics ─────────────────────────
_IC = {}


def icon_pil(name, px, color):
    S = 8
    N = max(px, 2) * S
    u = N / 24.0
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    P = lambda *v: [x * u for x in v]

    def line(*pts, w=2.2):
        wp = int(w * u)
        d.line(P(*pts), fill=color, width=wp, joint="curve")
        for i in range(0, len(pts), 2):
            x, y, r = pts[i] * u, pts[i + 1] * u, wp / 2
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def rpoly(*pts):
        d.polygon(P(*pts), fill=color)
        line(*pts, pts[0], pts[1], w=1.5)

    if name == "play":
        rpoly(8, 5, 19, 12, 8, 19)
    elif name == "pause":
        d.rounded_rectangle(P(6, 5, 10.2, 19), radius=u * 1.3, fill=color)
        d.rounded_rectangle(P(13.8, 5, 18, 19), radius=u * 1.3, fill=color)
    elif name == "next":
        rpoly(6, 6, 16, 12, 6, 18)
        d.rounded_rectangle(P(16.5, 5.5, 19.5, 18.5), radius=u, fill=color)
    elif name == "prev":
        rpoly(18, 6, 8, 12, 18, 18)
        d.rounded_rectangle(P(4.5, 5.5, 7.5, 18.5), radius=u, fill=color)
    elif name == "shuffle":
        line(3, 7, 7, 7, 17, 17, w=2)
        line(3, 17, 7, 17, 10.2, 13.2, w=2)
        line(13.8, 10.8, 17, 7, w=2)
        d.polygon(P(17, 3.6, 21.6, 7, 17, 10.4), fill=color)
        d.polygon(P(17, 13.6, 21.6, 17, 17, 20.4), fill=color)
    elif name in ("repeat", "repeat1"):
        line(5, 12, 5, 9, 7, 7, 17, 7, w=2)
        line(19, 12, 19, 15, 17, 17, 7, 17, w=2)
        d.polygon(P(16.5, 3.6, 21, 7, 16.5, 10.4), fill=color)
        d.polygon(P(7.5, 13.6, 3, 17, 7.5, 20.4), fill=color)
        if name == "repeat1":
            line(10.9, 10.7, 12.9, 9.5, 12.9, 14.5, w=1.7)
    elif name in ("vol1", "vol2", "mute"):
        d.polygon(P(3, 9.5, 7, 9.5, 12, 5.5, 12, 18.5, 7, 14.5, 3, 14.5), fill=color)
        if name == "vol1":
            d.arc(P(9, 7.5, 18, 16.5), -55, 55, fill=color, width=int(2 * u))
        elif name == "vol2":
            d.arc(P(9, 7.5, 18, 16.5), -55, 55, fill=color, width=int(2 * u))
            d.arc(P(8, 5.5, 21, 18.5), -52, 52, fill=color, width=int(2 * u))
        else:
            line(15, 9.5, 20.5, 15, w=2)
            line(20.5, 9.5, 15, 15, w=2)
    elif name == "plus":
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif name == "folder":
        d.rounded_rectangle(P(3, 7, 21, 19), radius=2.2 * u, fill=color)
        d.rounded_rectangle(P(3, 4.6, 11, 10), radius=1.6 * u, fill=color)
    elif name == "note":
        d.ellipse(P(4.5, 14.5, 11, 21), fill=color)
        d.rectangle(P(9.4, 5, 11.5, 18), fill=color)
        d.polygon(P(11.5, 5, 19.5, 7.5, 19.5, 11.5, 11.5, 9), fill=color)
    elif name == "search":
        d.ellipse(P(3.5, 3.5, 16, 16), outline=color, width=int(2.2 * u))
        line(14.5, 14.5, 20.5, 20.5)
    elif name == "close":
        line(6.5, 6.5, 17.5, 17.5, w=2)
        line(17.5, 6.5, 6.5, 17.5, w=2)
    elif name == "trash":
        d.rounded_rectangle(P(4.5, 6, 19.5, 8.2), radius=u, fill=color)
        d.rounded_rectangle(P(9, 3.5, 15, 6.5), radius=u, fill=color)
        d.polygon(P(6.5, 9.4, 17.5, 9.4, 16.6, 20, 7.4, 20), fill=color)
    return im.resize((px, px), Image.LANCZOS)


def icon(name, px, color):
    k = (name, px, color)
    if k not in _IC:
        _IC[k] = ImageTk.PhotoImage(icon_pil(name, px, color))
    return _IC[k]


def circle_btn(size, bg, glyph, gcolor):
    k = ("cb", size, bg, glyph, gcolor)
    if k not in _IC:
        S = 4
        im = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((0, 0, size * S - 1, size * S - 1), fill=bg)
        im = im.resize((size, size), Image.LANCZOS)
        g = icon_pil(glyph, int(size * 0.5), gcolor)
        off = (size - g.width) // 2
        im.alpha_composite(g, (off + (1 if glyph == "play" else 0), off))
        _IC[k] = ImageTk.PhotoImage(im)
    return _IC[k]


_MASK = {}


def round_mask(size, r):
    k = (size, r)
    if k not in _MASK:
        S = 4
        m = Image.new("L", (size * S, size * S), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, size * S - 1, size * S - 1), r * S, fill=255)
        _MASK[k] = m.resize((size, size), Image.LANCZOS)
    return _MASK[k]


def round_cover(pil, size, r):
    im = ImageOps.fit(pil.convert("RGB"), (size, size), Image.LANCZOS).convert("RGBA")
    im.putalpha(round_mask(size, r))
    return im


def logo_pil(size=256):
    """Melora app logo (also used as window / taskbar icon)"""
    g = Image.linear_gradient("L").resize((size, size))
    lg = Image.composite(Image.new("RGB", (size, size), h2r("#ec4899")),
                         Image.new("RGB", (size, size), h2r(BRAND)), g).convert("RGBA")
    n = icon_pil("note", int(size * .55), "#ffffff")
    off = (size - n.width) // 2
    lg.alpha_composite(n, (off, off))
    lg.putalpha(round_mask(size, int(size * .25)))
    return lg


def gen_cover(seed, size=512):
    h = int(hashlib.md5(seed.encode("utf8", "ignore")).hexdigest(), 16)
    h1 = (h % 360) / 360.0
    h2 = (h1 * 360 + 30 + (h >> 9) % 60) % 360 / 360.0
    c1 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(h1, .62, .92))
    c2 = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(h2, .82, .40))
    g = Image.linear_gradient("L").resize((size, size))
    im = Image.composite(Image.new("RGB", (size, size), c2), Image.new("RGB", (size, size), c1), g)
    glow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow).ellipse((size * .05, -size * .25, size * .95, size * .5), fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(size / 7))
    im = Image.composite(Image.new("RGB", (size, size), (255, 255, 255)), im, glow)
    nt = icon_pil("note", int(size * .40), (255, 255, 255, 215))
    im.paste(nt, ((size - nt.width) // 2, (size - nt.height) // 2), nt)
    return im


def dominant(im, lift=False):
    try:
        sm = im.convert("RGB").resize((48, 48))
        qi = sm.quantize(6)
        pal = qi.getpalette()
        best, bs = None, -1
        for cnt, idx in qi.getcolors():
            r, g, b = pal[idx * 3:idx * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            sc = cnt * (0.15 + s) * ((0.3 + v) if v > 0.18 else 0.05)
            if sc > bs:
                bs, best = sc, (h, s, v)
        h, s, v = best
        s, v = max(s, .45), min(max(v, .70), .95)
        rgb = [c * 255 for c in colorsys.hsv_to_rgb(h, s, v)]
        lum = .299 * rgb[0] + .587 * rgb[1] + .114 * rgb[2]
        if lift and lum < 150:              # keep UI accent readable on dark bg
            t = (150 - lum) / (255 - lum)
            rgb = [c + (255 - c) * t for c in rgb]
        return r2h(rgb)
    except Exception:
        return BRAND


def read_cover(path):
    try:
        mf = MutagenFile(path)
        data = None
        if mf is not None:
            if getattr(mf, "pictures", None):
                data = mf.pictures[0].data
            elif mf.tags is not None:
                t = mf.tags
                if hasattr(t, "getall") and t.getall("APIC"):
                    data = t.getall("APIC")[0].data
                elif "covr" in t:
                    data = bytes(t["covr"][0])
        if data:
            return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        pass
    d = Path(path).parent
    for n in ("cover", "folder", "front", "album", "Cover", "Folder", "Front"):
        for e in (".jpg", ".jpeg", ".png"):
            p = d / (n + e)
            if p.exists():
                try:
                    return Image.open(p).convert("RGB")
                except Exception:
                    pass
    return None


def read_meta(path):
    title, artist, dur = Path(path).stem, "", 0.0
    try:
        mf = MutagenFile(path, easy=True)
        if mf is not None:
            if mf.info:
                dur = mf.info.length
            if mf.get("title"):
                title = mf["title"][0]
            if mf.get("artist"):
                artist = mf["artist"][0]
    except Exception:
        pass
    if title == Path(path).stem or not artist:
        try:
            mf = MutagenFile(path)
            t = getattr(mf, "tags", None)
            if t is not None and hasattr(t, "get"):
                if t.get("TIT2") and title == Path(path).stem:
                    title = str(t["TIT2"])
                if t.get("TPE1") and not artist:
                    artist = str(t["TPE1"])
            if not dur and mf is not None and mf.info:
                dur = mf.info.length
        except Exception:
            pass
    return (title, artist, dur)


# ───────────────────────── tween engine ─────────────────────────
class Tweener:
    def __init__(self, root):
        self.root, self.tw, self.running = root, {}, False

    def run(self, key, a, b, ms, cb, ease=smooth, done=None):
        self.tw[key] = [time.perf_counter(), a, b, max(ms, 1) / 1000.0, cb, ease, done]
        if not self.running:
            self.running = True
            self.root.after(0, self._step)

    def _step(self):
        now = time.perf_counter()
        for k in list(self.tw):
            e = self.tw.get(k)
            if e is None:
                continue
            st, a, b, d, cb, ease, done = e
            t = min(1.0, (now - st) / d)
            try:
                cb(a + (b - a) * ease(t))
            except tk.TclError:
                self.tw.clear()
                break
            if t >= 1.0 and self.tw.get(k) is e:
                self.tw.pop(k, None)
                if done:
                    done()
        if self.tw:
            self.root.after(15, self._step)
        else:
            self.running = False


# ───────────────────────── application ─────────────────────────
class App:
    def __init__(self):
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Melora.MusicPlayer")
            except Exception:
                pass
        r = self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        r.title("Melora")
        r.geometry("1180x740")
        r.minsize(980, 640)
        r.configure(bg=BG)
        try:
            r.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        pygame.mixer.init()
        self.tw = Tweener(r)
        self.ff = pick_font(r)
        self._fonts = {}

        # data / state
        self.playlists, self.volume, self.view_pl = {}, 0.7, None
        self.shuffle, self.repeat, self.muted = False, 0, False
        self.load_data()
        if not self.playlists:
            self.playlists["My Playlist"] = []
        if self.view_pl not in self.playlists:
            self.view_pl = next(iter(self.playlists))
        self.play_pl, self.play_idx, self.state = None, -1, "stopped"
        self.offset, self.duration, self.cur = 0.0, 0.0, None
        self.meta, self._pending, self._meta_dirty = {}, set(), False
        self.covers = {}
        self.sel = -1

        # visual state
        self.acc, self.hdr_col = BRAND, BRAND
        self.hvals, self.mouse = {}, {"sb": (0, 0), "mv": (0, 0), "bar": (0, 0)}
        self.hover = {"sb": (), "mv": (), "bar": ()}
        self.hot = {"sb": [], "mv": [], "bar": []}
        self.scroll = self.scroll_t = 0.0
        self.sb_scroll, self.sbv, self._sbhide, self._sc_run = 0, 0.0, None, False
        self.rin, self.dropv, self.press = 0.0, 0.0, 0.0
        self.toast_text, self.toast_v, self._toast_after = "", 0.0, None
        self.eq = [0.1] * 5
        self.cov_cur, self.bar_cover_tk, self.view_cover_tk = None, None, None
        self._hg = (None, None)
        self.drag, self.seek_frac = None, None
        self.seek_x, self.vol_x = (0, 1), (0, 1)
        self.dirty, self._flush_sched = set(), False
        self.W = self.H = 0
        self.thumbs = {}
        self.query, self.qvar, self.search_open = "", tk.StringVar(), False
        self.sfocus, self._idx_key, self.idx, self._sp = 0.0, None, [], None
        self.thumb_y, self.thumb_h, self.drag_off = 4, 46, 0

        # widgets
        self.sb = tk.Canvas(r, width=SB_W, bg=SIDEBAR, highlightthickness=0)
        self.mv = tk.Canvas(r, bg=BG, highlightthickness=0)
        self.bar = tk.Canvas(r, height=BAR_H, bg=PANEL, highlightthickness=0)
        r.grid_columnconfigure(1, weight=1)
        r.grid_rowconfigure(0, weight=1)
        self.sb.grid(row=0, column=0, sticky="ns")
        self.mv.grid(row=0, column=1, sticky="nsew")
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.cv = {"sb": self.sb, "mv": self.mv, "bar": self.bar}
        self.sb.grid_propagate(False)
        self.search_entry = tk.Entry(
            self.mv, textvariable=self.qvar, bg=PILL, fg=TEXT, insertbackground=TEXT, relief="flat",
            bd=0, highlightthickness=0, font=self.f(14), selectbackground=BRAND, selectforeground="white")
        self.qvar.trace_add("write", lambda *a: self.on_query())
        self.search_entry.bind("<FocusIn>", lambda e: self.search_focus(True))
        self.search_entry.bind("<FocusOut>", lambda e: self.search_focus(False))
        self.search_entry.bind("<Escape>", lambda e: self.close_search())

        sh = Image.new("RGBA", (190 + 80, 190 + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((40, 40, 230, 230), 16, fill=(0, 0, 0, 170))
        self.shadow_tk = ImageTk.PhotoImage(sh.filter(ImageFilter.GaussianBlur(16)))
        self.logo_tk = ImageTk.PhotoImage(logo_pil(152).resize((38, 38), Image.LANCZOS))
        self._win_icons = [ImageTk.PhotoImage(logo_pil(sz)) for sz in (256, 64, 32)]
        try:
            r.iconphoto(True, *self._win_icons)       # window + taskbar icon
        except tk.TclError:
            pass

        for nm, cv in self.cv.items():
            cv.bind("<Motion>", lambda e, n=nm: self.on_motion(n, e))
            cv.bind("<Leave>", lambda e, n=nm: self.on_leave(n))
            cv.bind("<Button-1>", lambda e, n=nm: self.on_press(n, e))
            cv.bind("<B1-Motion>", lambda e, n=nm: self.on_drag(n, e))
            cv.bind("<ButtonRelease-1>", lambda e, n=nm: self.on_release(n, e))
            cv.bind("<Double-Button-1>", lambda e, n=nm: self.on_double(n, e))
            cv.bind("<Button-3>", lambda e, n=nm: self.on_right(n, e))
            cv.bind("<Button-2>", lambda e, n=nm: self.on_right(n, e))
            cv.bind("<MouseWheel>", lambda e, n=nm: self.on_wheel(n, e))
            cv.bind("<Button-4>", lambda e, n=nm: self.on_wheel(n, e, 1))
            cv.bind("<Button-5>", lambda e, n=nm: self.on_wheel(n, e, -1))
            cv.bind("<Configure>", lambda e, n=nm: self.on_configure(n))

        if HAS_DND:
            for w in (r, self.sb, self.mv, self.bar):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", self.on_drop_enter)
                w.dnd_bind("<<DropLeave>>", self.on_drop_leave)

        def g(fn):
            return lambda e: None if isinstance(e.widget, tk.Entry) else fn()
        r.bind("<space>", g(self.toggle_play))
        r.bind("<Delete>", g(lambda: self.remove_row(self.sel)))
        r.bind("<Left>", g(lambda: self.seek_rel(-5)))
        r.bind("<Right>", g(lambda: self.seek_rel(5)))
        r.bind("<Control-Left>", g(self.prev_track))
        r.bind("<Control-Right>", g(self.next_track))
        r.bind("<Up>", g(lambda: self.set_volume(self.volume + .05)))
        r.bind("<Down>", g(lambda: self.set_volume(self.volume - .05)))
        r.bind("m", g(self.toggle_mute))
        r.bind("<Control-f>", lambda e: self.open_search())
        r.bind("<Control-F>", lambda e: self.open_search())
        r.protocol("WM_DELETE_WINDOW", self.on_close)

        pygame.mixer.music.set_volume(self.volume)
        self.set_view(self.view_pl, animate=False)
        r.update()
        dark_titlebar(r)
        self.tw.run("fade", 0, 1, 450, self._set_alpha)
        self.tw.run("rin", 0, 1, 700, self._set_rin, out_cubic)
        self.ticker()

    # ───── fonts / small utils ─────
    def f(self, px, bold=False):
        k = (px, bold)
        if k not in self._fonts:
            self._fonts[k] = tkfont.Font(family=self.ff, size=-px, weight="bold" if bold else "normal")
        return self._fonts[k]

    def fit(self, font, text, maxw):
        if font.measure(text) <= maxw:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid] + "…") <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "…"

    def _set_alpha(self, v):
        try:
            self.root.attributes("-alpha", v)
        except tk.TclError:
            pass

    def _set_rin(self, v):
        self.rin = v
        self.request("mv")

    # ───── persistence ─────
    def load_data(self):
        try:
            d = json.loads((DATA_FILE if DATA_FILE.exists() else OLD_DATA).read_text(encoding="utf-8"))
            self.playlists = {k: [p for p in v if os.path.exists(p)]
                              for k, v in d.get("playlists", {}).items()}
            self.volume = d.get("volume", .7)
            self.shuffle = d.get("shuffle", False)
            self.repeat = d.get("repeat", 0)
            self.view_pl = d.get("view")
        except Exception:
            pass

    def save_data(self):
        try:
            DATA_FILE.write_text(json.dumps(
                {"playlists": self.playlists, "volume": self.volume, "shuffle": self.shuffle,
                 "repeat": self.repeat, "view": self.view_pl}, indent=1), encoding="utf-8")
        except Exception:
            pass

    def on_close(self):
        self.save_data()
        try:
            pygame.mixer.quit()
        finally:
            self.root.destroy()

    # ───── redraw scheduling ─────
    def request(self, *names):
        self.dirty.update(names)
        if not self._flush_sched:
            self._flush_sched = True
            self.root.after(8, self._flush)

    def _flush(self):
        self._flush_sched = False
        d, self.dirty = self.dirty, set()
        if "mv" in d:
            self.draw_mv()
        if "sb" in d:
            self.draw_sb()
        if "bar" in d:
            self.draw_bar()

    def on_configure(self, nm):
        if nm == "mv":
            self.W, self.H = self.mv.winfo_width(), self.mv.winfo_height()
            self.scroll_t = clamp(self.scroll_t, 0, self.max_scroll())
            self.scroll = clamp(self.scroll, 0, self.max_scroll())
        self.request(nm)

    # ───── hover system ─────
    def hv(self, nm, key):
        return self.hvals.get((nm, key), 0.0)

    def hover_to(self, nm, key, target, ms=150):
        k = (nm, key)
        cur = self.hvals.get(k, 0.0)
        if abs(cur - target) < 1e-3:
            return

        def cb(v):
            self.hvals[k] = v
            self.request(nm)
        self.tw.run(("hv", k), cur, target, ms, cb)

    def keys_for(self, name):
        if name is None:
            return ()
        if isinstance(name, tuple) and name[0] in ("rowplay", "del"):
            return (("row", name[1]), name)
        return (name,)

    def hit(self, nm, x, y):
        for x1, y1, x2, y2, name in reversed(self.hot[nm]):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None

    def on_motion(self, nm, e):
        self.mouse[nm] = (e.x, e.y)
        keys = self.keys_for(self.hit(nm, e.x, e.y))
        old = self.hover[nm]
        if keys != old:
            for k in old:
                if k not in keys:
                    self.hover_to(nm, k, 0)
            for k in keys:
                if k not in old:
                    self.hover_to(nm, k, 1)
            self.hover[nm] = keys
            self.cv[nm].config(cursor="hand2" if keys and keys != ("noop",) else "")
        if nm == "bar" and "seek" in keys:
            self.request("bar")

    def on_leave(self, nm):
        for k in self.hover[nm]:
            self.hover_to(nm, k, 0)
        self.hover[nm] = ()
        self.cv[nm].config(cursor="")

    # ───── events ─────
    def on_press(self, nm, e):
        n = self.hit(nm, e.x, e.y)
        self.cv[nm].focus_set()
        if nm == "bar" and n in ("seek", "vol"):
            self.drag = n
            self.drag_move(e)
            return
        if nm == "mv" and n == "scrollthumb":
            self.drag, self.drag_off = "scroll", e.y - self.thumb_y
            self.request("mv")
            return
        if nm == "mv" and n == "scrolltrack":
            self.scroll_by(self.H * .85 * (1 if e.y > self.thumb_y else -1))
            return
        if n is not None:
            self.activate(nm, n)

    def on_drag(self, nm, e):
        if self.drag:
            self.drag_move(e)

    def drag_move(self, e):
        if self.drag == "seek":
            x0, x1 = self.seek_x
            self.seek_frac = clamp((e.x - x0) / (x1 - x0))
            self.request("bar")
        elif self.drag == "vol":
            x0, x1 = self.vol_x
            self.muted = False
            self.set_volume(clamp((e.x - x0) / (x1 - x0)))
        elif self.drag == "scroll":
            span = max(1, self.H - 8 - self.thumb_h)
            v = clamp((e.y - self.drag_off - 4) / span) * self.max_scroll()
            self.scroll = self.scroll_t = v
            self.sbv = 1.0
            self.request("mv")

    def on_release(self, nm, e):
        if self.drag == "seek" and self.seek_frac is not None:
            self.on_seek(self.seek_frac)
        self.drag, self.seek_frac = None, None
        self.request("bar")

    def on_double(self, nm, e):
        n = self.hit(nm, e.x, e.y)
        if nm == "mv" and isinstance(n, tuple) and n[0] == "row":
            self.play_pl = self.view_pl
            self.play_index(n[1])
        elif nm == "sb" and isinstance(n, tuple) and n[0] == "pl":
            self.set_view(n[1])
            self.play_view()

    def on_wheel(self, nm, e, direction=None):
        d = direction if direction is not None else (e.delta / 120.0 if abs(e.delta) >= 120 else e.delta / 3.0)
        if nm == "mv":
            self.scroll_by(-d * 90)
        elif nm == "sb":
            mx = max(0, 116 + len(self.playlists) * 46 - (self.sb.winfo_height() - 130))
            self.sb_scroll = clamp(self.sb_scroll - d * 40, 0, mx)
            self.request("sb")
        elif nm == "bar":
            self.set_volume(self.volume + d * .04)

    def on_right(self, nm, e):
        n = self.hit(nm, e.x, e.y)
        if not isinstance(n, tuple):
            return
        m = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=TEXT, bd=0, relief="flat",
                    activebackground=BRAND, activeforeground="white", font=(self.ff, 10))
        if nm == "mv" and n[0] in ("row", "rowplay", "del"):
            i = n[1]
            self.sel = i
            self.request("mv")
            m.add_command(label="Play", command=lambda: (setattr(self, "play_pl", self.view_pl), self.play_index(i)))
            m.add_command(label="Show in folder", command=lambda: reveal(self.playlists[self.view_pl][i]))
            m.add_separator()
            m.add_command(label="Remove from playlist", command=lambda: self.remove_row(i))
        elif nm == "sb" and n[0] == "pl":
            name = n[1]
            m.add_command(label="Play", command=lambda: (self.set_view(name), self.play_view()))
            m.add_command(label="Rename…", command=lambda: self.rename_playlist(name))
            m.add_separator()
            m.add_command(label="Delete", command=lambda: self.delete_playlist(name))
        else:
            return
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def activate(self, nm, n):
        if n == "play":
            self.press = 1.0
            self.tw.run("press", 1.0, 0.0, 280, lambda v: (setattr(self, "press", v), self.request("bar")), out_cubic)
            self.toggle_play()
        elif n == "prev":
            self.prev_track()
        elif n == "next":
            self.next_track()
        elif n == "shuffle":
            self.shuffle = not self.shuffle
            self.save_data()
            self.request("bar", "mv")
        elif n == "repeat":
            self.repeat = (self.repeat + 1) % 3
            self.save_data()
            self.request("bar")
        elif n == "mute":
            self.toggle_mute()
        elif n == "bigplay":
            self.play_view()
        elif n in ("addfiles",):
            self.add_files_dialog()
        elif n in ("addfolder", "folder_card"):
            self.add_folder_dialog()
        elif n == "search":
            self.open_search()
        elif n == "clearsearch":
            self.qvar.set("")
            self.search_entry.focus_set()
        elif n == "newpl":
            self.new_playlist()
        elif isinstance(n, tuple):
            if n[0] == "pl":
                self.set_view(n[1])
            elif n[0] in ("row", "rowplay"):
                self.sel = n[1]
                if n[0] == "rowplay":
                    self.play_pl = self.view_pl
                    self.play_index(n[1])
                self.request("mv")
            elif n[0] == "del":
                self.remove_row(n[1])

    # ───── dialogs ─────
    def dialog(self, title, msg, entry=False, initial="", ok="OK", danger=False):
        top = tk.Toplevel(self.root)
        top.withdraw()
        top.configure(bg=PANEL)
        top.title(title)
        top.resizable(False, False)
        top.transient(self.root)
        res = {"v": None}
        tk.Label(top, text=title, bg=PANEL, fg=TEXT, font=self.f(19, True), anchor="w").pack(
            fill="x", padx=26, pady=(24, 4))
        if msg:
            tk.Label(top, text=msg, bg=PANEL, fg=SUB, font=self.f(13), anchor="w", justify="left",
                     wraplength=340).pack(fill="x", padx=26)
        ent = None
        if entry:
            ent = tk.Entry(top, bg=BG, fg=TEXT, insertbackground=TEXT, relief="flat", font=self.f(15),
                           highlightthickness=2, highlightbackground=BORDER, highlightcolor=BRAND,
                           selectbackground=BRAND, selectforeground="white")
            ent.pack(fill="x", padx=26, pady=(14, 0), ipady=8)
            ent.insert(0, initial)
            ent.select_range(0, "end")
        row = tk.Frame(top, bg=PANEL)
        row.pack(fill="x", padx=26, pady=22)

        def done(v):
            res["v"] = v
            top.destroy()

        def mk(text, bg, fg, cmd, hov):
            b = tk.Button(row, text=text, command=cmd, bg=bg, fg=fg, activebackground=hov,
                          activeforeground=fg, relief="flat", bd=0, font=self.f(13, True),
                          padx=22, pady=8, cursor="hand2")
            b.bind("<Enter>", lambda e: b.config(bg=hov))
            b.bind("<Leave>", lambda e: b.config(bg=bg))
            return b
        okb = mk(ok, "#e5484d" if danger else BRAND, "white",
                 lambda: done(ent.get() if ent else True), "#f26065" if danger else "#9d78f8")
        okb.pack(side="right")
        mk("Cancel", PANEL, SUB, lambda: done(None), HOVER).pack(side="right", padx=(0, 8))
        top.bind("<Return>", lambda e: okb.invoke())
        top.bind("<Escape>", lambda e: done(None))
        top.update_idletasks()
        w, h = 400, top.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 3
        top.geometry(f"{w}x{h}+{x}+{y}")
        dark_titlebar(top)
        top.deiconify()
        try:
            top.wait_visibility()
            top.grab_set()
        except tk.TclError:
            pass
        (ent or top).focus_set()
        top.wait_window()
        return res["v"]

    def toast(self, msg):
        self.toast_text = msg

        def up(v):
            self.toast_v = v
            self.request("mv")
        self.tw.run("toast", self.toast_v, 1, 260, up, out_cubic)
        if self._toast_after:
            self.root.after_cancel(self._toast_after)
        self._toast_after = self.root.after(2600, lambda: self.tw.run("toast", self.toast_v, 0, 320, up))

    # ───── playlists ─────
    def unique(self, base):
        name, n = base, 2
        while name in self.playlists:
            name, n = f"{base} ({n})", n + 1
        return name

    def new_playlist(self):
        name = self.dialog("New playlist", "Give your playlist a name.", entry=True, initial="My playlist", ok="Create")
        if name and name.strip():
            name = self.unique(name.strip())
            self.playlists[name] = []
            self.set_view(name)
            self.save_data()

    def rename_playlist(self, old):
        new = self.dialog("Rename playlist", "", entry=True, initial=old, ok="Save")
        if new and new.strip() and new.strip() != old:
            new = self.unique(new.strip())
            self.playlists = {(new if k == old else k): v for k, v in self.playlists.items()}
            self.view_pl = new if self.view_pl == old else self.view_pl
            self.play_pl = new if self.play_pl == old else self.play_pl
            self.thumbs.pop(old, None)
            self.save_data()
            self.request("sb", "mv")

    def delete_playlist(self, name):
        if not self.dialog("Delete playlist", f"“{name}” will be removed. Your music files are not deleted.",
                           ok="Delete", danger=True):
            return
        if self.play_pl == name:
            self.stop()
            self.play_pl, self.play_idx = None, -1
        del self.playlists[name]
        if not self.playlists:
            self.playlists["My Playlist"] = []
        if self.view_pl == name:
            self.set_view(next(iter(self.playlists)))
        self.save_data()
        self.request("sb", "mv")

    def set_view(self, name, animate=True):
        self.view_pl = name
        self.sel = -1
        if self.query:
            self.qvar.set("")
        self.search_open = False
        self.scroll = self.scroll_t = 0.0
        tr = self.playlists[name]
        self.ensure_meta(tr)
        pil = self.get_cover(tr[0]) if tr else None
        pil = pil or gen_cover(name)
        self.view_cover_tk = ImageTk.PhotoImage(round_cover(pil, 190, 14))
        self.tween_color("hdr_col", dominant(pil))
        if animate:
            self.tw.run("rin", 0, 1, 650, self._set_rin, out_cubic)
        self.request("mv", "sb")

    def tween_color(self, attr, new):
        old = getattr(self, attr)

        def cb(v):
            setattr(self, attr, mix(old, new, v))
            self.request("mv", "bar", "sb")
        self.tw.run(attr, 0, 1, 650, cb)

    # ───── tracks / meta ─────
    def ensure_meta(self, paths):
        todo = [p for p in paths if p not in self.meta and p not in self._pending]
        if todo:
            self._pending.update(todo)
            threading.Thread(target=self._meta_worker, args=(todo,), daemon=True).start()

    def _meta_worker(self, todo):
        for p in todo:
            self.meta[p] = read_meta(p)
            self._pending.discard(p)
            self._meta_dirty = True

    def get_meta(self, path):
        return self.meta.get(path) or (Path(path).stem, "", 0.0)

    def get_cover(self, path):
        if path not in self.covers:
            im = read_cover(path)
            if im is not None:
                im.thumbnail((600, 600))
            if len(self.covers) > 80:
                self.covers.clear()
            self.covers[path] = im
        return self.covers[path]

    def add_paths(self, paths, playlist=None):
        playlist = playlist or self.view_pl
        lst, n = self.playlists[playlist], 0
        for p in paths:
            if p not in lst:
                lst.append(p)
                n += 1
        self.ensure_meta(paths)
        self.save_data()
        self.request("mv", "sb")
        return n

    def add_files_dialog(self):
        files = filedialog.askopenfilenames(
            title="Add music files",
            filetypes=[("Audio", " ".join("*" + e for e in sorted(AUDIO_EXT))), ("All files", "*.*")])
        if files:
            n = self.add_paths(files)
            self.set_view(self.view_pl, animate=False)
            self.toast(f"Added {n} song{'s' if n != 1 else ''}")

    def add_folder_dialog(self):
        folder = filedialog.askdirectory(title="Choose a music folder")
        if folder:
            self.import_folder(folder)

    def import_folder(self, folder, autoplay=True):
        songs = scan_folder(folder)
        if not songs:
            self.toast("No audio files found in that folder")
            return
        name = self.unique(Path(folder).name or "Folder")
        self.playlists[name] = []
        self.add_paths(songs, name)
        self.set_view(name)
        self.toast(f"“{name}” · {len(songs)} songs")
        if autoplay:
            self.play_pl = name
            self.play_index(0 if not self.shuffle else random.randrange(len(songs)))

    def remove_row(self, i):
        tr = self.playlists.get(self.view_pl, [])
        if not (0 <= i < len(tr)):
            return
        del tr[i]
        if self.play_pl == self.view_pl:
            if i == self.play_idx:
                self.stop()
                self.play_idx = -1
            elif i < self.play_idx:
                self.play_idx -= 1
        self.sel = -1
        self.save_data()
        self.request("mv", "sb")

    # drag & drop
    def on_drop_enter(self, e):
        self.tw.run("drop", self.dropv, 1, 200, self._set_drop, out_cubic)
        return e.action

    def on_drop_leave(self, e):
        self.tw.run("drop", self.dropv, 0, 200, self._set_drop)
        return e.action

    def _set_drop(self, v):
        self.dropv = v
        self.request("mv")

    def on_drop(self, e):
        self.tw.run("drop", self.dropv, 0, 150, self._set_drop)
        added = False
        for item in self.root.tk.splitlist(e.data):
            if os.path.isdir(item):
                self.import_folder(item)
            elif Path(item).suffix.lower() in AUDIO_EXT:
                self.add_paths([item])
                added = True
        if added:
            self.set_view(self.view_pl, animate=False)
            self.toast("Added to playlist")
        return e.action

    # ───── playback ─────
    @property
    def queue(self):
        return self.playlists.get(self.play_pl, [])

    def play_view(self):
        tr = self.playlists[self.view_pl]
        if self.play_pl == self.view_pl and self.state != "stopped":
            return self.toggle_play()
        if tr:
            self.play_pl = self.view_pl
            self.play_index(random.randrange(len(tr)) if self.shuffle else 0)

    def play_index(self, i):
        q_ = self.queue
        if not (0 <= i < len(q_)):
            return
        path = q_[i]
        if not os.path.exists(path):
            self.toast("File not found")
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        except Exception as ex:
            self.toast(f"Cannot play: {ex}")
            return
        self.play_idx, self.offset, self.state = i, 0.0, "playing"
        if path not in self.meta:
            self.meta[path] = read_meta(path)
        title, artist, dur = self.meta[path]
        self.duration = dur
        self.cur = {"path": path, "title": title, "artist": artist}
        pil = self.get_cover(path) or gen_cover(title + artist)
        self.tween_color("acc", dominant(pil, lift=True))
        new = ImageOps.fit(pil.convert("RGB"), (64, 64), Image.LANCZOS)
        old = self.cov_cur or Image.new("RGB", (64, 64), h2r(CARD))
        self.cov_cur = new

        def cb(v):
            self.bar_cover_tk = ImageTk.PhotoImage(round_cover(Image.blend(old, new, v), 64, 10))
            self.request("bar")
        self.tw.run("cover", 0, 1, 450, cb)
        self.request("mv", "sb", "bar")

    def toggle_play(self):
        if self.state == "playing":
            pygame.mixer.music.pause()
            self.state = "paused"
        elif self.state == "paused":
            pygame.mixer.music.unpause()
            self.state = "playing"
        else:
            tr = self.playlists[self.view_pl]
            if tr:
                self.play_pl = self.view_pl
                self.play_index(self.sel if 0 <= self.sel < len(tr) else 0)
        self.request("mv", "sb", "bar")

    def stop(self):
        pygame.mixer.music.stop()
        self.state = "stopped"
        self.request("mv", "sb", "bar")

    def next_track(self, auto=False):
        n = len(self.queue)
        if n == 0:
            return
        if auto and self.repeat == 2:
            return self.play_index(self.play_idx)
        if self.shuffle and n > 1:
            i = random.choice([k for k in range(n) if k != self.play_idx])
        else:
            i = self.play_idx + 1
            if i >= n:
                if auto and self.repeat == 0:
                    return self.stop()
                i = 0
        self.play_index(i)

    def prev_track(self):
        if not self.queue:
            return
        if self.position() > 3:
            return self.play_index(self.play_idx)
        self.play_index((self.play_idx - 1) % len(self.queue))

    def position(self):
        if self.state == "stopped":
            return 0.0
        return self.offset + max(0, pygame.mixer.music.get_pos()) / 1000.0

    def on_seek(self, frac):
        if self.state == "stopped" or self.duration <= 0:
            return
        target = frac * self.duration
        try:
            pygame.mixer.music.play(start=target)
            self.offset = target
            if self.state == "paused":
                pygame.mixer.music.pause()
        except Exception:
            pass

    def seek_rel(self, d):
        if self.state != "stopped" and self.duration > 0:
            self.on_seek(clamp((self.position() + d) / self.duration))

    def set_volume(self, v):
        self.volume = clamp(v)
        pygame.mixer.music.set_volume(0 if self.muted else self.volume)
        self.request("bar")

    def toggle_mute(self):
        self.muted = not self.muted
        pygame.mixer.music.set_volume(0 if self.muted else self.volume)
        self.request("bar")

    def ticker(self):
        t = time.time()
        playing = self.state == "playing"
        for k in range(5):
            tgt = (0.2 + 0.8 * abs(math.sin(t * (2.3 + k * .85) + k * 1.9)) *
                   (0.6 + 0.4 * math.sin(t * 1.1 + k))) if playing else 0.1
            self.eq[k] += (tgt - self.eq[k]) * 0.35
        if playing:
            if not pygame.mixer.music.get_busy():
                self.next_track(auto=True)
            self.request("bar", "sb")
            if self.play_pl == self.view_pl:
                self.request("mv")
        if self._meta_dirty:
            self._meta_dirty = False
            self.request("mv", "sb")
        self.root.after(45, self.ticker)

    # ───── search ─────
    def open_search(self):
        self.search_open = True
        self.request("mv")
        self.root.after(30, lambda: (self.search_entry.focus_set(), self.search_entry.select_range(0, "end")))

    def close_search(self):
        self.qvar.set("")
        self.search_open = False
        self.mv.focus_set()
        self.request("mv")

    def search_focus(self, on):
        if not on and not self.query:
            self.search_open = False
        self.tw.run("sfocus", self.sfocus, 1.0 if on else 0.0, 160,
                    lambda v: (setattr(self, "sfocus", v), self.request("mv")))
        self.request("mv")

    def on_query(self):
        self.query = self.qvar.get().strip().lower()
        if self.query:
            self.search_open = True
            self.scroll_t = clamp(ROW0 - 80, 0, self.max_scroll())
            if not self._sc_run:
                self._sc_run = True
                self._sc_step()
        self.tw.run("rin", 0, 1, 420, self._set_rin, out_cubic)
        self.request("mv")

    def get_idx(self):
        tr = self.playlists.get(self.view_pl, [])
        key = (self.query, self.view_pl, len(tr), len(self.meta))
        if key != self._idx_key:
            self._idx_key = key
            if not self.query:
                self.idx = list(range(len(tr)))
            else:
                terms = self.query.split()
                out = []
                for i, p in enumerate(tr):
                    t, a, _ = self.get_meta(p)
                    hay = f"{t} {a} {Path(p).stem}".lower()
                    if all(x in hay for x in terms):
                        out.append(i)
                self.idx = out
        return self.idx

    # ───── scrolling ─────
    def max_scroll(self):
        n = len(self.get_idx())
        return max(0, ROW0 + n * RH + 30 - max(self.H, 1))

    def scroll_by(self, dy):
        self.scroll_t = clamp(self.scroll_t + dy, 0, self.max_scroll())
        self.tw.run("sbv", self.sbv, 1, 120, self._set_sbv)
        if self._sbhide:
            self.root.after_cancel(self._sbhide)
        self._sbhide = self.root.after(900, lambda: self.tw.run("sbv", self.sbv, 0, 400, self._set_sbv))
        if not self._sc_run:
            self._sc_run = True
            self._sc_step()

    def _set_sbv(self, v):
        self.sbv = v
        self.request("mv")

    def _sc_step(self):
        d = self.scroll_t - self.scroll
        if abs(d) < 0.4:
            self.scroll, self._sc_run = self.scroll_t, False
            return self.request("mv")
        self.scroll += d * 0.22
        self.request("mv")
        self.root.after(14, self._sc_step)

    # ───── drawing: shared bits ─────
    def eq_bars(self, c, x, y, color, n=4, w=3, gap=2, h=16):
        for k in range(n):
            bh = max(2, int(self.eq[k] * h))
            x1 = x + k * (w + gap)
            c.create_rectangle(x1, y - bh, x1 + w, y, fill=color, outline="")

    def hdr_image(self, W):
        key = (W, self.hdr_col)
        if self._hg[0] != key:
            h = HDR + 70
            top, bot = h2r(mix(BG, self.hdr_col, .46)), h2r(BG)
            col = Image.new("RGB", (1, h))
            px = col.load()
            for y in range(h):
                k = (y / (h - 1)) ** .85
                px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3))
            self._hg = (key, ImageTk.PhotoImage(col.resize((W, h))))
        return self._hg[1]

    # ───── drawing: main view ─────
    def draw_mv(self):
        c = self.mv
        W, H = c.winfo_width(), c.winfo_height()
        if W < 80 or H < 80:
            return
        self.W, self.H = W, H
        c.delete("all")
        hot = self.hot["mv"] = []
        sc = self.scroll
        tracks = self.playlists[self.view_pl]
        n = len(tracks)
        idx = self.get_idx()
        m = len(idx)
        c.create_image(0, -sc, anchor="nw", image=self.hdr_image(W))

        if sc < HDR + 80:
            c.create_image(36 - 40, 44 - 40 + 18 - sc, anchor="nw", image=self.shadow_tk)
            c.create_image(36, 44 - sc, anchor="nw", image=self.view_cover_tk)
            c.create_text(256, 82 - sc, text="PLAYLIST", font=self.f(12, True), fill=mix(SUB, TEXT, .4), anchor="w")
            tw_max = W - 256 - 40
            for px in (54, 42, 32, 26):
                tf = self.f(px, True)
                if tf.measure(self.view_pl) <= tw_max:
                    break
            c.create_text(256, 128 - sc, text=self.fit(tf, self.view_pl, tw_max), font=tf, fill=TEXT, anchor="w")
            tot = sum(self.get_meta(p)[2] for p in tracks)
            sub = (f"{m} of {n} songs" if self.query else f"{n} song{'s' if n != 1 else ''}") + \
                  (f"   ·   {fmt_long(tot)}" if tot else "")
            c.create_text(258, 176 - sc, text=sub, font=self.f(14), fill=SUB, anchor="w")

            by = 228 - sc
            here = self.play_pl == self.view_pl and self.state == "playing"
            hq = q(self.hv("mv", "bigplay"), 5)
            size = int(58 + 4 * hq)
            img = circle_btn(size, mix(BRAND, "#a98bff", hq), "pause" if here else "play", "#ffffff")
            c.create_image(256 + 29, by, image=img)
            hot.append((256, by - 30, 256 + 58, by + 30, "bigplay"))
            hs = q(self.hv("mv", "shuffle"))
            c.create_image(346, by, image=icon("shuffle", 26, BRAND_HI if self.shuffle else mix(SUB, TEXT, hs)))
            if self.shuffle:
                c.create_oval(344, by + 18, 348, by + 22, fill=self.acc, outline="")
            hot.append((330, by - 20, 364, by + 24, "shuffle"))
            px_ = 386
            for label, ic, name, w in (("Add files", "plus", "addfiles", 120), ("Add folder", "folder", "addfolder", 132)):
                hvv = self.hv("mv", name)
                hq2 = q(hvv)
                rr(c, px_, by - 20, px_ + w, by + 20, 20, fill=mix("#1d1d28", "#2c2c3d", hvv), outline="")
                c.create_image(px_ + 22, by, image=icon(ic, 16, mix(SUB, TEXT, hq2)))
                c.create_text(px_ + 42, by, text=label, font=self.f(13, True), fill=mix(SUB, TEXT, hvv), anchor="w")
                hot.append((px_, by - 20, px_ + w, by + 20, name))
                px_ += w + 10

        # column header
        hy = HDR + 14 - sc
        c.create_text(50, hy, text="#", font=self.f(12, True), fill=DIM)
        c.create_text(88, hy, text="TITLE", font=self.f(11, True), fill=DIM, anchor="w")
        c.create_text(W - 88, hy, text="TIME", font=self.f(11, True), fill=DIM, anchor="e")
        c.create_line(30, hy + 18, W - 30, hy + 18, fill=BORDER)

        if n == 0:
            cy = ROW0 + 90 - sc
            c.create_image(W // 2, cy, image=icon("folder", 54, DIM))
            c.create_text(W // 2, cy + 52, text="This playlist is empty", font=self.f(20, True), fill=TEXT)
            msg = ("Drag & drop a folder anywhere in this window, or" if HAS_DND
                   else "Add some music to get started  (pip install tkinterdnd2 for drag & drop)")
            c.create_text(W // 2, cy + 82, text=msg, font=self.f(14), fill=SUB)
            hvv = self.hv("mv", "addfolder")
            rr(c, W // 2 - 80, cy + 108, W // 2 + 80, cy + 150, 21, fill=mix(BRAND, "#a98bff", hvv), outline="")
            c.create_text(W // 2, cy + 129, text="Browse folder", font=self.f(14, True), fill="white")
            hot.append((W // 2 - 80, cy + 108, W // 2 + 80, cy + 150, "addfolder"))
        elif m == 0:
            cy = ROW0 + 90 - sc
            c.create_image(W // 2, cy, image=icon("search", 54, DIM))
            c.create_text(W // 2, cy + 52, text="No results", font=self.f(20, True), fill=TEXT)
            c.create_text(W // 2, cy + 82, text=f"Nothing matches “{self.qvar.get().strip()}”",
                          font=self.f(14), fill=SUB)

        first = max(0, int((sc - ROW0) // RH))
        last = min(m, int((sc + H - ROW0) // RH) + 1)
        tf, af, nf = self.f(15, True), self.f(13), self.f(14)
        title_w = W - 88 - 150 - 140
        for k in range(first, last):
            i = idx[k]
            p = out_cubic(clamp(self.rin * 1.7 - min(k, 14) * .08))
            y0 = ROW0 + k * RH - sc
            y = y0 + (1 - p) * 14
            hvv = self.hv("mv", ("row", i))
            title, artist, dur = self.get_meta(tracks[i])
            cur = self.play_pl == self.view_pl and i == self.play_idx and self.state != "stopped"
            base = SELROW if i == self.sel else BG
            fill = mix(base, HOVER, hvv)
            if fill != BG:
                rr(c, 16, y + 2, W - 16, y + RH - 2, 10, fill=fill, outline="")
            mid = y + RH / 2
            if cur:
                self.eq_bars(c, 41, mid + 8, self.acc if p > .5 else BG)
            elif hvv > .35:
                c.create_image(50, mid, image=icon("play", 18, mix(BG, TEXT, p)))
            else:
                c.create_text(50, mid, text=str(i + 1), font=nf, fill=mix(BG, SUB, p))
            c.create_text(88, mid - 10, text=self.fit(tf, title, title_w), font=tf, anchor="w",
                          fill=mix(BG, self.acc if cur else TEXT, p))
            c.create_text(88, mid + 11, text=self.fit(af, artist or "Unknown artist", title_w), font=af,
                          anchor="w", fill=mix(BG, SUB, p))
            c.create_text(W - 88, mid, text=fmt_time(dur) if dur else "–:––", font=nf, anchor="e",
                          fill=mix(BG, SUB, p))
            dv = self.hv("mv", ("del", i))
            if hvv > .02:
                c.create_image(W - 50, mid, image=icon("trash", 18, mix(mix(BG, DIM, hvv), "#ff6b72", q(dv))))
            hot.append((16, y0, W - 16, y0 + RH, ("row", i)))
            hot.append((30, y0, 72, y0 + RH, ("rowplay", i)))
            hot.append((W - 72, y0 + 6, W - 30, y0 + RH - 6, ("del", i)))

        # sticky top bar (appears when scrolled)
        bv = clamp((sc - 70) / 90)
        if sc > 60:
            hot.append((0, 0, W, 64, "noop"))
        if bv > .01:
            barc = mix(BG, "#14141d", bv)
            c.create_rectangle(0, 0, W, 64, fill=barc, outline="")
            c.create_line(0, 64, W, 64, fill=mix(barc, BORDER, bv))
            tfn = self.f(20, True)
            c.create_text(36, 33, text=self.fit(tfn, self.view_pl, max(60, W - 520)), font=tfn,
                          fill=mix(barc, TEXT, bv), anchor="w")

        # draggable scrollbar
        ms = self.max_scroll()
        if ms > 0:
            th = max(46, (H - 8) * H / (ms + H))
            ty = 4 + sc / ms * (H - 8 - th)
            self.thumb_y, self.thumb_h = ty, th
            hvv = max(self.hv("mv", "scrollthumb"), 1.0 if self.drag == "scroll" else 0.0)
            act = max(hvv, self.sbv)
            wd = 6 + 4 * hvv
            if hvv > .02:
                rr(c, W - 7 - wd, 4, W - 3, H - 4, (wd + 4) / 2, fill=mix(BG, "#15151d", hvv), outline="")
            col = mix("#303042", mix("#7d7d9c", self.acc, .4 * hvv), clamp(.3 + .7 * act))
            rr(c, W - 5 - wd, ty, W - 5, ty + th, wd / 2, fill=col, outline="")
            hot.append((W - 22, 0, W, H, "scrolltrack"))
            hot.append((W - 22, ty, W, ty + th, "scrollthumb"))

        # search pill
        pw = int(clamp(W * .27, 210, 340))
        x2 = W - 36
        x1 = x2 - pw
        sy_ = 37
        shv = self.hv("mv", "search")
        rr(c, x1, sy_ - 20, x2, sy_ + 20, 20, fill=PILL,
           outline=mix(mix("#242431", "#3a3a52", shv), BRAND_HI, self.sfocus))
        c.create_image(x1 + 23, sy_, image=icon("search", 18, mix(DIM, BRAND_HI, max(self.sfocus, shv * .5))))
        hot.append((x1, sy_ - 20, x2, sy_ + 20, "search"))
        if self.search_open or self.query:
            sp = (int(x1 + 42), sy_ - 11, int(pw - 42 - (40 if self.query else 18)))
            if self._sp != sp:
                self._sp = sp
                self.search_entry.place(x=sp[0], y=sp[1], width=sp[2], height=22)
        else:
            if self._sp is not None:
                self._sp = None
                self.search_entry.place_forget()
            c.create_text(x1 + 42, sy_, text="Search songs…", font=self.f(14), fill=DIM, anchor="w")
        if self.query:
            chv = self.hv("mv", "clearsearch")
            c.create_image(x2 - 22, sy_, image=icon("close", 16, mix(DIM, TEXT, q(chv))))
            hot.append((x2 - 38, sy_ - 16, x2 - 8, sy_ + 16, "clearsearch"))

        # drop overlay
        if self.dropv > .02:
            v = self.dropv
            ins = 20 - 8 * v
            rr(c, ins, ins, W - ins, H - ins, 22, fill=mix(BG, "#16112b", 1), outline=mix(BG, BRAND_HI, v),
               width=2, dash=(10, 8))
            c.create_image(W // 2, H // 2 - 40 + (1 - v) * 18, image=icon("folder", 72, mix("#16112b", BRAND_HI, v)))
            c.create_text(W // 2, H // 2 + 28, text="Drop to play", font=self.f(30, True), fill=mix("#16112b", TEXT, v))
            c.create_text(W // 2, H // 2 + 66, text="Folders become playlists instantly", font=self.f(15),
                          fill=mix("#16112b", SUB, v))

        # toast
        if self.toast_v > .02:
            v = self.toast_v
            tfn = self.f(14, True)
            w = tfn.measure(self.toast_text) + 56
            ty = H - 40 + (1 - v) * 24
            rr(c, W / 2 - w / 2, ty - 21, W / 2 + w / 2, ty + 21, 21, fill=mix(BG, "#262638", v),
               outline=mix(BG, self.acc, v * .6))
            c.create_text(W / 2, ty, text=self.toast_text, font=tfn, fill=mix(BG, TEXT, v))

    # ───── drawing: sidebar ─────
    def thumb(self, name):
        if name not in self.thumbs:
            self.thumbs[name] = ImageTk.PhotoImage(round_cover(gen_cover(name, 96), 34, 9))
        return self.thumbs[name]

    def draw_sb(self):
        c = self.sb
        H = c.winfo_height()
        if H < 100:
            return
        c.delete("all")
        hot = self.hot["sb"] = []
        c.create_line(SB_W - 1, 0, SB_W - 1, H, fill=BORDER)
        c.create_image(24, 24, anchor="nw", image=self.logo_tk)
        c.create_text(72, 43, text="Melora", font=self.f(24, True), fill=TEXT, anchor="w")
        c.create_text(26, 100, text="PLAYLISTS", font=self.f(11, True), fill=DIM, anchor="w")
        hq = self.hv("sb", "newpl")
        if hq > .02:
            c.create_oval(SB_W - 50, 88, SB_W - 22, 116, fill=mix(SIDEBAR, HOVER, hq), outline="")
        c.create_image(SB_W - 36, 102, image=icon("plus", 18, mix(DIM, TEXT, q(hq))))
        hot.append((SB_W - 52, 86, SB_W - 20, 118, "newpl"))

        top, bottom = 126, H - 124
        nf, sf = self.f(15, True), self.f(12)
        for i, (name, tr) in enumerate(self.playlists.items()):
            y = top + i * 48 - self.sb_scroll
            if y < top - 48 or y > bottom:
                continue
            hvv = self.hv("sb", ("pl", name))
            sel = name == self.view_pl
            fill = mix(mix(SIDEBAR, SELROW, 1 if sel else 0), HOVER, hvv)
            if fill != SIDEBAR:
                rr(c, 12, y, SB_W - 12, y + 44, 12, fill=fill, outline="")
            if sel:
                rr(c, 12, y + 12, 15, y + 32, 2, fill=self.acc, outline="")
            c.create_image(26, y + 5, anchor="nw", image=self.thumb(name))
            c.create_text(70, y + 16, text=self.fit(nf, name, SB_W - 70 - 52), font=nf, anchor="w",
                          fill=TEXT if (sel or hvv > .3) else mix(SUB, TEXT, .5))
            c.create_text(70, y + 33, text=f"{len(tr)} songs", font=sf, anchor="w", fill=DIM)
            if self.play_pl == name and self.state != "stopped":
                self.eq_bars(c, SB_W - 40, y + 30, self.acc, n=3, w=3, gap=2, h=14)
            hot.append((12, y, SB_W - 12, y + 44, ("pl", name)))

        # bottom card
        cy1, cy2 = H - 108, H - 20
        hvv = self.hv("sb", "folder_card")
        rr(c, 16, cy1, SB_W - 16, cy2, 16, fill=mix("#0f0f15", "#161624", hvv),
           outline=mix(TRACK, self.acc, hvv), width=1, dash=(5, 5))
        c.create_image(SB_W // 2, cy1 + 26, image=icon("folder", 28, mix(DIM, BRAND_HI, hvv)))
        txt = "Drop a folder to play" if HAS_DND else "Add a music folder"
        c.create_text(SB_W // 2, cy1 + 56, text=txt, font=self.f(14, True), fill=mix(SUB, TEXT, hvv))
        c.create_text(SB_W // 2, cy1 + 74, text="or click to browse", font=self.f(12), fill=DIM)
        hot.append((16, cy1, SB_W - 16, cy2, "folder_card"))

    # ───── drawing: player bar ─────
    def draw_bar(self):
        c = self.bar
        W = c.winfo_width()
        if W < 400:
            return
        c.delete("all")
        hot = self.hot["bar"] = []
        c.create_line(0, 0, W, 0, fill=BORDER)
        cx = W // 2

        # now playing
        if self.bar_cover_tk:
            c.create_image(20, 16, anchor="nw", image=self.bar_cover_tk)
        else:
            rr(c, 20, 16, 84, 80, 10, fill=CARD, outline="")
            c.create_image(52, 48, image=icon("note", 26, DIM))
        tx, maxw = 100, max(60, cx - 250 - 100)
        if self.cur:
            c.create_text(tx, 40, text=self.fit(self.f(16, True), self.cur["title"], maxw),
                          font=self.f(16, True), fill=TEXT, anchor="w")
            c.create_text(tx, 60, text=self.fit(self.f(13), self.cur["artist"] or "Unknown artist", maxw),
                          font=self.f(13), fill=SUB, anchor="w")
        else:
            c.create_text(tx, 48, text="Nothing playing", font=self.f(15, True), fill=DIM, anchor="w")

        # transport
        cy = 30

        def ib(name, x, key, active=False, size=22):
            hq = q(self.hv("bar", key))
            col = BRAND_HI if active else mix(SUB, TEXT, hq)
            c.create_image(x, cy, image=icon(name, size, col))
            if active:
                c.create_oval(x - 2, cy + 19, x + 2, cy + 23, fill=self.acc, outline="")
            hot.append((x - 20, cy - 20, x + 20, cy + 22, key))
        ib("shuffle", cx - 116, "shuffle", self.shuffle)
        ib("prev", cx - 58, "prev", size=26)
        hq = q(self.hv("bar", "play"), 5)
        size = int(round(46 + 3 * hq - 4 * self.press))
        c.create_image(cx, cy, image=circle_btn(size, "#ffffff", "pause" if self.state == "playing" else "play", "#0a0a0f"))
        hot.append((cx - 25, cy - 25, cx + 25, cy + 25, "play"))
        ib("next", cx + 58, "next", size=26)
        ib("repeat1" if self.repeat == 2 else "repeat", cx + 116, "repeat", self.repeat > 0)

        # seek
        x0, x1, sy = cx - 215, cx + 215, 78
        self.seek_x = (x0, x1)
        dur = self.duration if self.state != "stopped" else 0
        pos = self.position()
        frac = clamp(pos / dur) if dur > 0 else 0.0
        if self.seek_frac is not None:
            frac = self.seek_frac
            pos = frac * dur
        sh = max(self.hv("bar", "seek"), 1.0 if self.drag == "seek" else 0.0)
        c.create_text(x0 - 12, sy, text=fmt_time(pos), font=self.f(12), fill=SUB, anchor="e")
        c.create_text(x1 + 12, sy, text=fmt_time(dur), font=self.f(12), fill=SUB, anchor="w")
        t = 4 + 2 * sh
        c.create_line(x0, sy, x1, sy, width=t, fill=TRACK, capstyle="round")
        xv = x0 + (x1 - x0) * frac
        if frac > 0:
            c.create_line(x0, sy, xv, sy, width=t, fill=mix(TEXT, self.acc, sh), capstyle="round")
        if sh > .05:
            r = 6.5 * sh
            c.create_oval(xv - r, sy - r, xv + r, sy + r, fill=TEXT, outline="")
            if dur > 0 and "seek" in self.hover["bar"] and not self.drag:
                mx = clamp((self.mouse["bar"][0] - x0) / (x1 - x0))
                lab = fmt_time(mx * dur)
                lx = clamp(self.mouse["bar"][0], x0 + 22, x1 - 22)
                rr(c, lx - 24, sy - 34, lx + 24, sy - 14, 8, fill="#262638", outline="")
                c.create_text(lx, sy - 24, text=lab, font=self.f(12, True), fill=TEXT)
        hot.append((x0 - 6, sy - 12, x1 + 6, sy + 12, "seek"))

        # volume
        vx0, vx1, vy = W - 150, W - 30, 48
        self.vol_x = (vx0, vx1)
        eff = 0 if self.muted else self.volume
        ic = "mute" if eff == 0 else ("vol1" if eff < .5 else "vol2")
        c.create_image(vx0 - 26, vy, image=icon(ic, 22, mix(SUB, TEXT, q(self.hv("bar", "mute")))))
        hot.append((vx0 - 40, vy - 16, vx0 - 12, vy + 16, "mute"))
        vh = max(self.hv("bar", "vol"), 1.0 if self.drag == "vol" else 0.0)
        t = 4 + 2 * vh
        c.create_line(vx0, vy, vx1, vy, width=t, fill=TRACK, capstyle="round")
        xv = vx0 + (vx1 - vx0) * eff
        if eff > 0:
            c.create_line(vx0, vy, xv, vy, width=t, fill=mix(TEXT, self.acc, vh), capstyle="round")
        if vh > .05:
            r = 6 * vh
            c.create_oval(xv - r, vy - r, xv + r, vy + r, fill=TEXT, outline="")
        hot.append((vx0 - 6, vy - 12, vx1 + 6, vy + 12, "vol"))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()