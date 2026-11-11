"""Canal MIDI SysEx vers le script FL Studio (API WinMM via ctypes).

Le Python embarque dans FL Studio interdit les sockets et l'ecriture de
fichiers : le seul canal vers l'exterieur est le MIDI. Le script parle sur le
port virtuel « FL Cowork » ; cette application ouvre l'autre bout de la boucle
(« FL Cowork Bus »).

Trame : F0 7D <sens> <fin> <json ascii...> F7
  sens : 'S' (0x53) script -> application, 'A' (0x41) application -> script
  fin  : '1' (0x31) dernier fragment du message, '0' (0x30) fragment a suivre
"""
import ctypes
import json
import queue
import threading
import time
from ctypes import wintypes

FRAME = 480            # octets de charge utile par SysEx
MIM_LONGDATA = 0x3C4
CALLBACK_FUNCTION = 0x30000
MHDR_DONE = 1
DWORD_PTR = ctypes.c_size_t


class MIDIHDR(ctypes.Structure):
    _fields_ = [('lpData', ctypes.c_void_p), ('dwBufferLength', wintypes.DWORD),
                ('dwBytesRecorded', wintypes.DWORD), ('dwUser', DWORD_PTR), ('dwFlags', wintypes.DWORD),
                ('lpNext', ctypes.c_void_p), ('reserved', DWORD_PTR), ('dwOffset', wintypes.DWORD),
                ('dwReserved', DWORD_PTR * 8)]


class _InCaps(ctypes.Structure):
    _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD), ('v', wintypes.UINT),
                ('name', wintypes.WCHAR * 32), ('s', wintypes.DWORD)]


class _OutCaps(ctypes.Structure):
    _fields_ = [('wMid', wintypes.WORD), ('wPid', wintypes.WORD), ('v', wintypes.UINT),
                ('name', wintypes.WCHAR * 32), ('t', wintypes.WORD), ('vo', wintypes.WORD),
                ('n', wintypes.WORD), ('c', wintypes.WORD), ('s', wintypes.DWORD)]


_PROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, wintypes.UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR)
_w = ctypes.WinDLL('winmm')
_H = ctypes.c_void_p
_HDRP = ctypes.POINTER(MIDIHDR)
_w.midiInOpen.argtypes = [ctypes.POINTER(_H), wintypes.UINT, _PROC, DWORD_PTR, wintypes.DWORD]
_w.midiOutOpen.argtypes = [ctypes.POINTER(_H), wintypes.UINT, DWORD_PTR, DWORD_PTR, wintypes.DWORD]
for _n in ('midiInPrepareHeader', 'midiInUnprepareHeader', 'midiInAddBuffer',
           'midiOutPrepareHeader', 'midiOutUnprepareHeader', 'midiOutLongMsg'):
    getattr(_w, _n).argtypes = [_H, _HDRP, wintypes.UINT]
for _n in ('midiInStart', 'midiInStop', 'midiInReset', 'midiInClose', 'midiOutReset', 'midiOutClose'):
    getattr(_w, _n).argtypes = [_H]


def _find(name, inputs):
    n = _w.midiInGetNumDevs() if inputs else _w.midiOutGetNumDevs()
    for i in range(n):
        c = _InCaps() if inputs else _OutCaps()
        get = _w.midiInGetDevCapsW if inputs else _w.midiOutGetDevCapsW
        if get(i, ctypes.byref(c), ctypes.sizeof(c)) == 0 and c.name.strip().lower() == name.lower():
            return i
    return None


class MidiLink:
    """Liaison JSON bidirectionnelle sur SysEx. on_message(dict) est appele depuis un thread systeme."""

    def __init__(self, port_name, on_message):
        self.name = port_name
        self.on_message = on_message
        self.hin = _H()
        self.hout = _H()
        self.opened = False
        self.closing = False
        self.parts = []
        self.acc = bytearray()
        self.q = queue.Queue()
        self._cb = _PROC(self._callback)
        self._bufs = []
        self._thread = None

    def open(self):
        i, o = _find(self.name, True), _find(self.name, False)
        if i is None or o is None:
            return False
        if _w.midiInOpen(ctypes.byref(self.hin), i, self._cb, 0, CALLBACK_FUNCTION):
            return False
        if _w.midiOutOpen(ctypes.byref(self.hout), o, 0, 0, 0):
            _w.midiInClose(self.hin)
            return False
        for _ in range(16):
            buf = ctypes.create_string_buffer(4096)
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = 4096
            _w.midiInPrepareHeader(self.hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
            _w.midiInAddBuffer(self.hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
            self._bufs.append((buf, hdr))
        _w.midiInStart(self.hin)
        self.closing = False
        self.opened = True
        self._thread = threading.Thread(target=self._sender, daemon=True)
        self._thread.start()
        return True

    def close(self):
        if not self.opened:
            return
        self.closing = True
        self.opened = False
        self.q.put(None)
        _w.midiInStop(self.hin)
        _w.midiInReset(self.hin)
        for _, hdr in self._bufs:
            _w.midiInUnprepareHeader(self.hin, ctypes.byref(hdr), ctypes.sizeof(hdr))
        _w.midiInClose(self.hin)
        _w.midiOutReset(self.hout)
        _w.midiOutClose(self.hout)
        self._bufs = []

    def send(self, obj):
        if not self.opened:
            return
        raw = json.dumps(obj, separators=(',', ':')).encode('ascii')
        for i in range(0, len(raw), FRAME):
            last = i + FRAME >= len(raw)
            self.q.put(bytes((0xF0, 0x7D, 0x41, 0x31 if last else 0x30)) + raw[i:i + FRAME] + b'\xf7')

    def _sender(self):
        size = ctypes.sizeof(MIDIHDR)
        while True:
            frame = self.q.get()
            if frame is None or self.closing:
                return
            buf = ctypes.create_string_buffer(frame, len(frame))
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = hdr.dwBytesRecorded = len(frame)
            if _w.midiOutPrepareHeader(self.hout, ctypes.byref(hdr), size):
                continue
            _w.midiOutLongMsg(self.hout, ctypes.byref(hdr), size)
            end = time.time() + 1.0
            while not hdr.dwFlags & MHDR_DONE and time.time() < end:
                time.sleep(0.0005)
            _w.midiOutUnprepareHeader(self.hout, ctypes.byref(hdr), size)

    def _callback(self, handle, msg, instance, p1, p2):
        if msg != MIM_LONGDATA or self.closing:
            return
        try:
            hdr = ctypes.cast(p1, _HDRP).contents
            n = hdr.dwBytesRecorded
            if n:
                self.acc += ctypes.string_at(hdr.lpData, n)
                self._drain()
            _w.midiInAddBuffer(self.hin, ctypes.cast(p1, _HDRP), ctypes.sizeof(MIDIHDR))
        except Exception:
            pass

    def _drain(self):
        """Decoupe le flux recu en SysEx complets et reassemble les messages."""
        while True:
            end = self.acc.find(b'\xf7')
            if end < 0:
                if len(self.acc) > 1 << 20:
                    del self.acc[:]
                return
            frame = bytes(self.acc[:end])
            del self.acc[:end + 1]
            start = frame.rfind(b'\xf0')
            frame = frame[start + 1:] if start >= 0 else frame
            if len(frame) < 3 or frame[0] != 0x7D or frame[1] != 0x53:
                continue
            self.parts.append(frame[3:])
            if frame[2] == 0x31:
                raw = b''.join(self.parts)
                self.parts = []
                try:
                    self.on_message(json.loads(raw.decode('ascii')))
                except Exception:
                    pass
