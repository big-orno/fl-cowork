"""Liaison TCP de test : remplace le lien SysEx du script (les tests n'ont pas de port MIDI)."""
import json
import select
import socket


class TcpLink:
    def __init__(self, script, port):
        self.m = script
        self.port = port
        self.sock = None
        self.up = False
        self.buf = b''
        self.out = b''
        self.next_try = 0.0
        self.t0 = 0.0

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        self.up = False
        self.buf = self.out = b''
        self.m.ST['live'] = False

    def send(self, obj):
        if self.up:
            self.out += (json.dumps(obj, separators=(',', ':')) + '\n').encode('utf-8')

    def poll(self, now):
        m = self.m
        if self.sock is None:
            if now < self.next_try:
                return []
            self.next_try = now + 2.0
            k = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            k.setblocking(False)
            k.connect_ex(('127.0.0.1', self.port))
            self.sock = k
            self.t0 = now
            return []
        if not self.up:
            _, w, x = select.select([], [self.sock], [self.sock], 0)
            if x or (not w and now - self.t0 > 3.0):
                self.close()
                return []
            if not w:
                return []
            self.up = True
            m.S.clear()
            self.send({'t': 'hello', 'ver': m.VERSION, 'title': m.title()})
            m.ST['pres'] = None
            m.ST['fp'] = None
        msgs = []
        try:
            while True:
                d = self.sock.recv(65536)
                if not d:
                    self.close()
                    return msgs
                self.buf += d
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self.close()
            return msgs
        if b'\n' in self.buf:
            lines = self.buf.split(b'\n')
            self.buf = lines.pop()
            msgs = [json.loads(ln.decode('utf-8')) for ln in lines if ln]
        if self.out:
            try:
                n = self.sock.send(self.out)
                self.out = self.out[n:]
            except (BlockingIOError, InterruptedError):
                pass
            except OSError:
                self.close()
        return msgs
