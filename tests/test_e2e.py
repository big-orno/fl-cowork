"""Test de bout en bout : deux applications FL Cowork + deux faux FL Studio (synchro a l'enregistrement).

Lancement :  py -3.14 tests/test_e2e.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import mockfl  # noqa: E402
from tcplink import TcpLink  # noqa: E402
from cowork import env, flp  # noqa: E402


class Side:
    def __init__(self, name, port, tmp):
        self.name = name
        self.world = mockfl.World()
        self.home = os.path.join(tmp, name)
        self.docs = os.path.join(self.home, 'docs')
        os.makedirs(self.docs)
        e = dict(os.environ, LOCALAPPDATA=self.home, FLCOWORK_DOCS=self.docs,
                 FLCOWORK_BRIDGE_PORT=str(port), FLCOWORK_NO_LAUNCH='1', FLCOWORK_NO_UPNP='1', FLCOWORK_NO_MIDI='1', FLCOWORK_NO_DIALOG='1')
        self.proc = subprocess.Popen([sys.executable, '-m', 'cowork', '--no-ui'], cwd=ROOT, env=e)
        spec = importlib.util.spec_from_file_location('flscript_' + name,
                                                      os.path.join(ROOT, 'fl_script', 'device_FLCowork.py'))
        self.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.script)
        self.script.LINK = TcpLink(self.script, port)
        self.url = None

    def tick(self):
        mockfl.CUR = self.world
        self.script.OnIdle()

    def api(self, path, body=None):
        if not self.url:
            rt = os.path.join(self.home, 'FL Cowork', 'runtime.json')
            self.url = json.load(open(rt))['url']
        base, tok = self.url.split('/?t=')
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                     {'X-Token': tok})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())

    def act(self, op, **kw):
        r = self.api('/api/act', dict(kw, op=op))
        assert r.get('ok'), r
        return r

    def state(self):
        return self.api('/api/state')

    def load_project(self, stem):
        """Simule le chargement du projet de la session dans FL."""
        mockfl.CUR = self.world
        self.script.OnProjectLoad(0)
        self.world.title = 'FL Studio 2025 - ' + stem
        self.world.dirty = 0
        self.script.OnProjectLoad(100)


import struct  # noqa: E402


def note(pos):
    b = bytearray(24)
    struct.pack_into('<IHHIHH', b, 0, pos, 0, 0, 96, 60, 0)
    return bytes(b)


def set_notes(path, positions):
    """Simule un enregistrement dans FL : le piano roll du motif 1 contient ces notes."""
    data = open(path, 'rb').read()
    evs = [(e, r) for e, r in flp.events(data) if e != flp.NOTES]
    if not any(e == flp.NEW_PAT for e, _ in evs):
        k = next(i for i, (e, _) in enumerate(evs) if e == flp.PLAYLIST)
        evs.insert(k, (flp.NEW_PAT, bytes((1, 0))))
    k = next(i for i, (e, _) in enumerate(evs) if e == flp.NEW_PAT)
    evs.insert(k + 1, (flp.NOTES, b''.join(note(p) for p in positions)))
    with open(path, 'wb') as f:
        f.write(flp._build(flp._head(data), evs))


def get_notes(path):
    out, pat = [], None
    for e, r in flp.events(open(path, 'rb').read()):
        if e == flp.NEW_PAT:
            pat = r[0]
        elif e == flp.NOTES and pat == 1:
            out += [struct.unpack_from('<I', r, i)[0] for i in range(0, len(r), 24)]
    return sorted(out)


def main():
    tmp = tempfile.mkdtemp(prefix='flcowork-test-')
    a = Side('alice', 47901, tmp)
    b = Side('bob', 47902, tmp)
    sides = (a, b)
    step = [0]

    def pump(cond, what, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            for s in sides:
                s.tick()
            try:
                if cond():
                    step[0] += 1
                    print('  ok %2d  %s' % (step[0], what))
                    return
            except (KeyError, TypeError, IndexError, OSError, ValueError, struct.error):
                pass
            time.sleep(0.01)
        raise AssertionError('ECHEC : ' + what)

    try:
        pump(lambda: a.state()['fl'] and b.state()['fl'], 'les deux scripts FL se connectent a leur application')
        a.act('name', value='Alice')
        b.act('name', value='Bob')

        inst = env.fl_paths()[1]
        src = raw = None
        for d, _, files in os.walk(os.path.join(inst, 'Data', 'Templates')):
            for f in files:
                if f.lower().endswith('.flp'):
                    texts = [flp._text(r) for e, r in flp.events(open(os.path.join(d, f), 'rb').read()) if e == 196]
                    texts = [t for t in texts if t]
                    if texts:
                        src, raw = os.path.join(d, f), texts[0]
                        break
            if src:
                break
        assert src, 'aucun template FL avec sample trouve'
        os.makedirs(os.path.join(tmp, 'mes samples'))
        wav = os.path.join(tmp, 'mes samples', 'kick été.wav')
        with open(wav, 'wb') as f:
            f.write(b'RIFF' + os.urandom(150_000))
        proj = os.path.join(tmp, 'Mon Morceau.flp')
        flp.rewrite_samples(src, proj, {raw: wav})
        set_notes(proj, [0])
        a.act('host', path=proj)
        pump(lambda: a.state()['session']['rev']['n'] == 1, "l'hote publie la version 1")
        a.load_project('Mon Morceau')
        adir = a.state()['session']['dir']
        fa = os.path.join(adir, 'Mon Morceau.flp')

        code = a.act('code', ip='127.0.0.1')['code']
        b.act('join', code=code)
        pump(lambda: b.state()['session']['file_n'] == 1, "l'invite recoit le projet")
        bdir = b.state()['session']['dir']
        fb = os.path.join(bdir, 'Mon Morceau.flp')
        got = os.path.join(bdir, 'kick été.wav')
        assert open(got, 'rb').read() == open(wav, 'rb').read(), 'sample non recu'
        refs = flp.sample_refs(fb)
        assert any(os.path.normcase(pth) == os.path.normcase(got) for _, pth in refs), refs
        step[0] += 1
        print('  ok %2d  sample exterieur recu et relie au projet de l invite' % step[0])
        b.load_project('Mon Morceau')
        pump(lambda: all(s.state()['session']['live'] for s in sides), 'les deux sont prets')

        # B enregistre : A recoit
        set_notes(fb, [0, 96])
        pump(lambda: b.state()['session']['rev']['n'] == 2 and a.state()['session']['file_n'] == 2,
             "B enregistre (Ctrl+S) : A recoit la version 2")
        assert get_notes(fa) == [0, 96], get_notes(fa)
        a.load_project('Mon Morceau')

        # A enregistre : B recoit (dans l'autre sens)
        set_notes(fa, [0, 96, 192])
        pump(lambda: b.state()['session']['file_n'] == 3, "A enregistre (Ctrl+S) : B recoit la version 3")
        assert get_notes(fb) == [0, 96, 192], get_notes(fb)
        b.load_project('Mon Morceau')

        # travail simultane : chacun ajoute une note sans avoir recu l'autre
        n0 = a.state()['session']['rev']['n']
        set_notes(fa, [0, 96, 192, 288])
        set_notes(fb, [0, 96, 192, 384])
        want = [0, 96, 192, 288, 384]
        pump(lambda: get_notes(fa) == want and get_notes(fb) == want and a.state()['session']['file_n'] == b.state()['session']['file_n'] > n0,
             'enregistrements simultanes : les deux notes sont fusionnees chez les deux')
        time.sleep(1.0)
        pump(lambda: a.state()['session']['rev']['n'] == b.state()['session']['rev']['n'] == a.state()['session']['file_n'],
             'versions identiques, plus rien a publier')
        n = a.state()['session']['rev']['n']
        time.sleep(1.5)
        assert a.state()['session']['rev']['n'] == n, 'republication en boucle'
        step[0] += 1
        print('  ok %2d  stable : pas de republication en boucle' % step[0])

        b.act('chat', text='salut')
        pump(lambda: any(m.get('text') == 'salut' for m in a.state()['session']['chat']), 'discussion')
        b.act('leave')
        pump(lambda: len(a.state()['session']['peers']) == 1, 'depart de B')
        print("TOUS LES TESTS PASSENT")
    finally:
        for s in sides:
            try:
                s.act('quit')
            except Exception:
                pass
        time.sleep(0.5)
        for s in sides:
            if s.proc.poll() is None:
                s.proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
