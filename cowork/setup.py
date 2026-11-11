"""Installation : application, script FL Studio, raccourcis, port MIDI virtuel."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import winreg

from . import env

LOOPBACK_TRANSPORT = '{942BF02D-93C0-4EA8-B03E-D51156CA75E1}'   # Windows MIDI Services : loopback
ASSOCIATION = '{6F1C0A52-3B7E-4C55-9D2A-F1C0C0A0B001}'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\FLCowork'
MIDI_LOG = os.path.join(env.APPDIR, 'midi-setup.log')
NOWIN = 0x08000000


def msg(text, flags=0x40):
    return ctypes.windll.user32.MessageBoxW(None, text, env.APP, flags | 0x10000)


def install_script():
    d = env.script_dir()
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(env.resource('device_FLCowork.py'), os.path.join(d, 'device_FLCowork.py'))


def _shortcut(lnk, target):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
          "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Description='FL Cowork';$s.Save()"
          % (lnk.replace("'", "''"), target.replace("'", "''"), os.path.dirname(target).replace("'", "''")))
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], creationflags=NOWIN)


def _shortcut_paths():
    start = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs')
    desk = os.path.join(os.path.expanduser('~'), 'Desktop')
    return [os.path.join(start, 'FL Cowork.lnk'), os.path.join(desk, 'FL Cowork.lnk')]


def midi_setup():
    """(administrateur) Declare un port MIDI loopback 'FL Cowork' dans Windows MIDI Services.

    FL Studio ne charge un script que s'il est attache a une entree MIDI ; ce
    port virtuel transporte aussi les echanges script <-> application (SysEx), car
    le Python de FL Studio interdit les sockets.
    """
    os.makedirs(env.APPDIR, exist_ok=True)
    log = []
    try:
        key = r'SOFTWARE\Microsoft\Windows MIDI Services'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                name = winreg.QueryValueEx(k, 'CurrentConfig')[0]
            except OSError:
                name = ''
            folder = os.path.join(os.environ.get('ProgramData', r'C:\ProgramData'), 'Microsoft', 'MIDI')
            os.makedirs(folder, exist_ok=True)
            fresh = not name
            if fresh:
                name = 'Default.midiconfig.json'
            path = os.path.join(folder, name)
            cfg = None
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8-sig') as f:
                    cfg = json.load(f)
                shutil.copyfile(path, path + '.flcowork-backup')
            if not isinstance(cfg, dict):
                cfg = {'header': {'configName': 'Default', 'product': 'Windows MIDI Services', 'fileVersion': 1.0}}
            create = cfg.setdefault('endpointTransportPluginSettings', {}) \
                        .setdefault(LOOPBACK_TRANSPORT, {}).setdefault('create', {})
            if ASSOCIATION not in create:
                create[ASSOCIATION] = {
                    'endpointA': {'name': env.MIDI_PORT, 'description': 'Port virtuel pour FL Cowork',
                                  'uniqueIdentifier': 'FLCOWORKA'},
                    'endpointB': {'name': env.MIDI_BUS, 'description': 'Port virtuel pour FL Cowork',
                                  'uniqueIdentifier': 'FLCOWORKB'},
                }
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=2)
                log.append('config ecrite : ' + path)
            if fresh:
                winreg.SetValueEx(k, 'CurrentConfig', 0, winreg.REG_SZ, name)
        subprocess.run(['net', 'stop', 'midisrv', '/y'], creationflags=NOWIN, capture_output=True)
        r = subprocess.run(['net', 'start', 'midisrv'], creationflags=NOWIN, capture_output=True)
        log.append('service redemarre (code %d)' % r.returncode)
        log.append('OK')
    except Exception as e:
        log.append('ERREUR %s: %s' % (e.__class__.__name__, e))
    with open(MIDI_LOG, 'w', encoding='utf-8') as f:
        f.write('\n'.join(log))


def ensure_midi_port(wait=25):
    if env.midi_port_ready():
        return True
    try:
        os.remove(MIDI_LOG)
    except OSError:
        pass
    if not env.run_elevated('--midi-setup'):
        return False
    end = time.time() + wait
    while time.time() < end:
        time.sleep(1)
        if env.midi_port_ready():
            return True
    return False


def install(silent=False):
    if not silent and msg("Installer FL Cowork ?\n\n"
           "- l'application FL Cowork (dans votre profil)\n"
           "- le script « FL Cowork » pour FL Studio\n"
           "- un port MIDI virtuel « FL Cowork » (demande les droits administrateur ; "
           "le service MIDI de Windows redemarre brievement)", 0x21) != 1:
        return False
    os.makedirs(env.INSTALL_DIR, exist_ok=True)
    if env.FROZEN and os.path.normcase(sys.executable) != os.path.normcase(env.INSTALLED_EXE):
        try:
            shutil.copyfile(sys.executable, env.INSTALLED_EXE)
        except PermissionError:
            if not silent:
                msg("FL Cowork est en cours d'execution. Fermez-le puis relancez l'installation.", 0x30)
            return False
    try:
        install_script()
    except OSError as e:
        if not silent:
            msg("Impossible d'installer le script FL Studio :\n%s" % e, 0x30)
    for lnk in _shortcut_paths():
        _shortcut(lnk, env.INSTALLED_EXE)
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            winreg.SetValueEx(k, 'DisplayName', 0, winreg.REG_SZ, 'FL Cowork')
            winreg.SetValueEx(k, 'DisplayIcon', 0, winreg.REG_SZ, env.INSTALLED_EXE)
            winreg.SetValueEx(k, 'Publisher', 0, winreg.REG_SZ, 'FL Cowork')
            winreg.SetValueEx(k, 'UninstallString', 0, winreg.REG_SZ, '"%s" --uninstall' % env.INSTALLED_EXE)
            winreg.SetValueEx(k, 'NoModify', 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, 'NoRepair', 0, winreg.REG_DWORD, 1)
    except OSError:
        pass
    port = env.midi_port_ready() if silent else ensure_midi_port()
    if silent:
        return True
    text = "FL Cowork est installe.\n\nDerniere etape, une seule fois, dans FL Studio :\n" \
           "Options > MIDI settings > section Input > cliquez « FL Cowork » > " \
           "Controller type : « FL Cowork » > activez Enable.\n" \
           "(Redemarrez FL Studio s'il etait ouvert.)"
    if not port:
        text += "\n\nATTENTION : le port MIDI virtuel « FL Cowork » n'a pas pu etre cree " \
                "automatiquement. Installez loopMIDI (gratuit), creez un port nomme « FL Cowork », " \
                "puis suivez l'etape ci-dessus."
    msg(text, 0x40 if port else 0x30)
    return True


def uninstall():
    if msg('Desinstaller FL Cowork ?', 0x24) != 6:
        return
    shutil.rmtree(env.script_dir(), ignore_errors=True)
    for lnk in _shortcut_paths():
        try:
            os.remove(lnk)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    shutil.rmtree(env.APPDIR, ignore_errors=True)
    msg('FL Cowork est desinstalle. Vos sessions (Documents\\FL Cowork) sont conservees.')
    if env.FROZEN:
        subprocess.Popen('cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"' % env.INSTALL_DIR,
                         shell=True, creationflags=NOWIN)
