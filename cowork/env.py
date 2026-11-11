"""Chemins et integration Windows / FL Studio."""
import ctypes
import json
import os
import subprocess
import sys
import winreg
from ctypes import wintypes

APP = 'FL Cowork'
MIDI_PORT = 'FL Cowork'          # cote FL Studio
MIDI_BUS = 'FL Cowork Bus'       # cote application (autre bout de la boucle)
APPDIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), APP)
BLOBS = os.path.join(APPDIR, 'blobs')
CONFIG = os.path.join(APPDIR, 'config.json')
RUNTIME = os.path.join(APPDIR, 'runtime.json')
INSTALL_DIR = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', APP)
INSTALLED_EXE = os.path.join(INSTALL_DIR, 'FLCowork.exe')
FROZEN = getattr(sys, 'frozen', False)


def resource(name):
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (os.path.join(base, name), os.path.join(base, 'cowork', name), os.path.join(base, 'fl_script', name)):
        if os.path.exists(p):
            return p
    return os.path.join(base, name)


def _reg(root, key, name):
    try:
        with winreg.OpenKey(root, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def documents():
    d = _reg(winreg.HKEY_CURRENT_USER,
             r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders', 'Personal')
    return os.path.expandvars(d) if d else os.path.join(os.path.expanduser('~'), 'Documents')


def sessions_root():
    return os.environ.get('FLCOWORK_DOCS') or os.path.join(documents(), APP)


def fl_paths():
    """(exe FL Studio, dossier d'installation, dossier de donnees utilisateur FL)."""
    k = r'Software\Image-Line\Shared\Paths'
    exe = _reg(winreg.HKEY_CURRENT_USER, k, 'FL Studio') or ''
    inst = _reg(winreg.HKEY_CURRENT_USER, k, 'Install path') or os.path.dirname(exe)
    shared = _reg(winreg.HKEY_CURRENT_USER, k, 'Shared data') or os.path.join(documents(), 'Image-Line')
    return exe, inst, os.path.join(shared.rstrip('\\/'), 'FL Studio')


def script_dir():
    return os.path.join(fl_paths()[2], 'Settings', 'Hardware', APP)


def script_installed():
    return os.path.exists(os.path.join(script_dir(), 'device_FLCowork.py'))


def empty_template():
    inst = fl_paths()[1]
    root = os.path.join(inst, 'Data', 'Templates')
    best = None
    for d, _, files in os.walk(root):
        for f in files:
            if f.lower() == 'empty.flp':
                return os.path.join(d, f)
            if f.lower() == 'basic.flp' or (best is None and f.lower().endswith('.flp')):
                best = os.path.join(d, f)
    return best


def midi_inputs():
    class Caps(ctypes.Structure):
        _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD), ('v', wintypes.UINT),
                    ('name', wintypes.WCHAR * 32), ('s', wintypes.DWORD)]
    out = []
    try:
        w = ctypes.WinDLL('winmm')
        for i in range(w.midiInGetNumDevs()):
            c = Caps()
            if w.midiInGetDevCapsW(i, ctypes.byref(c), ctypes.sizeof(c)) == 0:
                out.append(c.name)
    except OSError:
        pass
    return out


def midi_port_ready():
    return any(MIDI_PORT.lower() in n.lower() for n in midi_inputs())


def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def self_command(*args):
    if FROZEN:
        return [sys.executable] + list(args)
    return [sys.executable, '-m', 'cowork'] + list(args)


def run_elevated(*args):
    """Relance ce programme en administrateur (invite UAC). Renvoie True si lance."""
    cmd = self_command(*args)
    params = subprocess.list2cmdline(cmd[1:])
    cwd = None if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = ctypes.windll.shell32.ShellExecuteW(None, 'runas', cmd[0], params, cwd, 0)
    return r > 32


def open_ui(url):
    for base in (os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')):
        edge = os.path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe')
        if base and os.path.exists(edge):
            subprocess.Popen([edge, '--app=' + url, '--window-size=470,820'])
            return
    import webbrowser
    webbrowser.open(url)


def pick_flp():
    """Boite de dialogue Windows 'Ouvrir' pour choisir un .flp. Renvoie '' si annule."""
    class OFN(ctypes.Structure):
        _fields_ = [('lStructSize', wintypes.DWORD), ('hwndOwner', wintypes.HWND),
                    ('hInstance', wintypes.HINSTANCE), ('lpstrFilter', ctypes.c_void_p),
                    ('lpstrCustomFilter', wintypes.LPWSTR), ('nMaxCustFilter', wintypes.DWORD),
                    ('nFilterIndex', wintypes.DWORD), ('lpstrFile', ctypes.c_void_p),
                    ('nMaxFile', wintypes.DWORD), ('lpstrFileTitle', wintypes.LPWSTR),
                    ('nMaxFileTitle', wintypes.DWORD), ('lpstrInitialDir', wintypes.LPCWSTR),
                    ('lpstrTitle', wintypes.LPCWSTR), ('Flags', wintypes.DWORD),
                    ('nFileOffset', wintypes.WORD), ('nFileExtension', wintypes.WORD),
                    ('lpstrDefExt', wintypes.LPCWSTR), ('lCustData', wintypes.LPARAM),
                    ('lpfnHook', ctypes.c_void_p), ('lpTemplateName', wintypes.LPCWSTR),
                    ('pvReserved', ctypes.c_void_p), ('dwReserved', wintypes.DWORD),
                    ('FlagsEx', wintypes.DWORD)]
    buf = ctypes.create_unicode_buffer(2048)
    filt = ctypes.create_unicode_buffer('Projets FL Studio (*.flp)\0*.flp\0\0')
    o = OFN()
    o.lStructSize = ctypes.sizeof(OFN)
    o.hwndOwner = ctypes.windll.user32.GetForegroundWindow()
    o.lpstrFilter = ctypes.cast(filt, ctypes.c_void_p)
    o.lpstrFile = ctypes.cast(buf, ctypes.c_void_p)
    o.nMaxFile = 2048
    o.lpstrTitle = 'Choisir le projet a partager'
    o.Flags = 0x1000 | 0x80000 | 0x8
    if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(o)):
        return buf.value
    return ''


def fl_window_title():
    """Titre de la fenetre principale de FL Studio (« projet.flp - FL Studio 2025 »), '' si absente.

    L'API de script de FL ne donne pas le nom du fichier projet ; la fenetre, si.
    """
    found = []
    u = ctypes.windll.user32

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value == 'TFruityLoopsMainForm':
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, buf, 512)
            found.append(buf.value)
            return False
        return True
    u.EnumWindows(each, 0)
    return found[0] if found else ''


def installed_plugins():
    """Noms (en minuscules) des plugins connus de ce FL Studio : natifs + VST scannes."""
    names = set()
    exe, inst, user = fl_paths()
    for kind in ('Generators', 'Effects'):
        d = os.path.join(inst, 'Plugins', 'Fruity', kind)
        if os.path.isdir(d):
            names.update(n.lower() for n in os.listdir(d))
    db = os.path.join(user, 'Presets', 'Plugin database', 'Installed')
    for d, _, files in os.walk(db):
        for f in files:
            if f.lower().endswith(('.nfo', '.fst')):
                names.add(os.path.splitext(f)[0].lower())
    return names


def message_box(text, warn=True):
    """Boite de dialogue non bloquante (au premier plan)."""
    import threading
    threading.Thread(target=ctypes.windll.user32.MessageBoxW, daemon=True,
                     args=(None, text, APP, (0x30 if warn else 0x40) | 0x10000 | 0x40000)).start()


_FL_VERSION = []


def fl_version():
    """Version de FL Studio installee, lue dans son modele de projet vide (« 25.1.5.4976 »)."""
    if not _FL_VERSION:
        v = ''
        try:
            from . import flp
            t = empty_template()
            if t:
                with open(t, 'rb') as f:
                    v = flp.version_of(f.read())
        except Exception:
            pass
        _FL_VERSION.append(v)
    return _FL_VERSION[0]


def dismiss_dialogs(seconds=25):
    """Repond tout seul aux questions de FL Studio apres l'ouverture d'un projet.

    « Enregistrer les modifications ? » -> Non (la version locale est deja
    sauvegardee a part) ; « projet d'une version plus recente » -> continuer.
    """
    import re
    import threading
    import time

    u = ctypes.windll.user32

    def text(h):
        b = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, b, 256)
        return re.sub(r'[&.]', '', b.value).strip().lower()

    def cls(h):
        b = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, b, 64)
        return b.value

    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def run():
        end = time.time() + seconds
        while time.time() < end:
            main, tops = [], []

            def top(h, _):
                if u.IsWindowVisible(h):
                    (main if cls(h) == 'TFruityLoopsMainForm' else tops).append(h)
                return True
            u.EnumWindows(EnumProc(top), 0)
            if main:
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(main[0], ctypes.byref(pid))
                for h in tops:
                    p = wintypes.DWORD()
                    u.GetWindowThreadProcessId(h, ctypes.byref(p))
                    if p.value != pid.value:
                        continue
                    btns = []

                    def kid(c, _):
                        if 'button' in cls(c).lower():
                            btns.append((c, text(c)))
                        return True
                    u.EnumChildWindows(h, EnumProc(kid), 0)
                    if not 2 <= len(btns) <= 4:
                        continue
                    pick = None
                    for c, t in btns:
                        if 'anyway' in t or 'quand même' in t or 'quand meme' in t:
                            pick = c
                    if pick is None:
                        for c, t in btns:
                            if re.match(r"^(no|non|don't save|do not save|ne pas enregistrer|discard)\b", t):
                                pick = c
                    if pick:
                        u.PostMessageW(pick, 0x00F5, 0, 0)    # BM_CLICK
            time.sleep(0.4)
    threading.Thread(target=run, daemon=True).start()
