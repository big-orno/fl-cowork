"""Test de bout en bout : deux applications FL Cowork + deux faux FL Studio.

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


def main():
    tmp = tempfile.mkdtemp(prefix='flcowork-test-')
    a = Side('alice', 47901, tmp)
    b = Side('bob', 47902, tmp)
    sides = (a, b)
    step = [0]

    def pump(cond, what, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            for s in sides:
                s.tick()
            try:
                if cond():
                    step[0] += 1
                    print('  ok %2d  %s' % (step[0], what))
                    return
            except (KeyError, TypeError, IndexError, OSError):
                pass
            time.sleep(0.005)
        raise AssertionError('ECHEC : ' + what)

    try:
        pump(lambda: a.state()['fl'] and b.state()['fl'], 'les deux scripts FL se connectent a leur application')
        a.act('name', value='Alice')
        b.act('name', value='Bob')

        # projet de test : un template FL dont un sample est redirige vers un fichier
        # hors du dossier de session (cas d'un sample perso absent chez l'autre)
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
        a.act('host', path=proj)
        pump(lambda: a.state()['session']['rev']['n'] == 1, "l'hote publie la version 1")
        a.load_project('Mon Morceau')
        pump(lambda: a.state()['session']['live'], "l'hote passe en direct")

        code = a.act('code', ip='127.0.0.1')['code']
        b.act('join', code=code)
        pump(lambda: b.state()['session']['file_n'] == 1, "l'invite recoit le projet")
        bdir = b.state()['session']['dir']
        got = os.path.join(bdir, 'kick été.wav')
        assert open(got, 'rb').read() == open(wav, 'rb').read(), 'sample non recu'
        refs = flp.sample_refs(os.path.join(bdir, 'Mon Morceau.flp'))
        assert any(os.path.normcase(pth) == os.path.normcase(got) for _, pth in refs), refs
        step[0] += 1
        print('  ok %2d  sample exterieur recu et relie au projet de l invite' % step[0])
        b.load_project('Mon Morceau')
        pump(lambda: b.state()['session']['live'] and a.state()['session']['live'], 'les deux sont en direct')
        ready = lambda: all(s.script.ST['live'] and not s.script.ST['warm'] for s in sides)  # noqa: E731
        pump(ready, 'reference initiale etablie')

        t0 = time.time()
        a.world.tracks[3]['v'] = 0.4321
        pump(lambda: b.world.tracks[3]['v'] == 0.4321, 'volume mixeur A -> B')
        print('         latence ~%d ms' % ((time.time() - t0) * 1000))
        b.world.chans[2]['n'] = 'Kick de Bob'
        b.world.tempo = 128.5
        b.world.tracks[5]['routes'][9] = 0.5
        b.world.chans[0]['params'][7] = 0.9
        pump(lambda: a.world.chans[2]['n'] == 'Kick de Bob' and a.world.tempo == 128.5
             and a.world.tracks[5]['routes'].get(9) == 0.5 and a.world.chans[0]['params'][7] == 0.9,
             'nom de canal, tempo, routage, parametre de plugin B -> A')

        a.world.grid[(1, 1)] = 0b10001
        pump(lambda: b.world.grid.get((1, 1)) == 0b10001, 'step sequencer A -> B (meme pattern)')
        a.world.pat = 2
        pump(lambda: a.script.ST['pat'] == 2, 'A passe au pattern 2')
        a.world.grid[(2, 0)] = 0b1111
        time.sleep(0.3)
        pump(lambda: b.script.DEFER.get(2), 'pas du pattern 2 mis en attente chez B (pattern 1 affiche)')
        b.world.pat = 2
        pump(lambda: b.world.grid.get((2, 0)) == 0b1111, 'pas appliques quand B ouvre le pattern 2')

        a.world.tracks[10]['p'] = -0.5
        b.world.tracks[10]['p'] = 0.7
        pump(lambda: a.world.tracks[10]['p'] == b.world.tracks[10]['p'], 'conflit simultane : convergence')
        time.sleep(0.5)
        pump(lambda: a.world.tracks[10]['p'] == b.world.tracks[10]['p'], 'conflit simultane : stable')
        print('         valeur retenue : %s' % a.world.tracks[10]['p'])

        b.act('chat', text='salut')
        pump(lambda: any(m.get('text') == 'salut' for m in a.state()['session']['chat']), 'discussion')

        # publication : A enregistre le projet (nouveau contenu sur le disque)
        adir = a.state()['session']['dir']
        with open(os.path.join(adir, 'Mon Morceau.flp'), 'ab') as f:
            f.write(b'\x00' * 7)
        with open(os.path.join(adir, 'kick.wav'), 'wb') as f:
            f.write(os.urandom(700_000))
        pump(lambda: b.state()['session']['file_n'] == 2, 'B recoit la version 2 (flp + sample)', 20)
        assert open(os.path.join(bdir, 'kick.wav'), 'rb').read() == open(os.path.join(adir, 'kick.wav'), 'rb').read()
        assert not b.state()['session']['live'], 'B ne doit pas etre en direct avant rechargement'
        b.load_project('Mon Morceau')
        pump(lambda: b.state()['session']['live'] and a.state()['session']['live'], 'direct retabli apres rechargement')
        pump(ready, 'reference retablie')
        a.world.tracks[20]['mu'] = 1
        pump(lambda: b.world.tracks[20]['mu'] == 1, 'synchro active sur la version 2')

        # structure divergente chez l'invite -> synchro suspendue
        b.world.chans.append(dict(b.world.chans[1], n='Nouveau'))
        pump(lambda: not b.state()['session']['live'], "ajout de canal local chez B : sa synchro est suspendue")
        b.world.chans.pop()
        pump(lambda: b.state()['session']['live'], 'structure retablie : synchro reprise')
        pump(ready, 'reference retablie')

        # plugin absent chez l'invite : alerte, mais la session continue
        a.world.focus_plugin = 0
        b.world.chans[0]['plugin'] = None
        pump(lambda: 'x.0' in b.script.SKIP and b.state()['session']['live'],
             'plugin manquant chez B : synchro maintenue, plugin exclu')
        pump(lambda: any('Il me manque : Sytrus' in m.get('text', '') for m in a.state()['session']['chat']),
             'A est prevenu du plugin manquant chez B')
        pump(ready, 'reference retablie')
        a.world.chans[0]['params'][3] = 0.123
        a.world.tracks[30]['v'] = 0.2222
        pump(lambda: b.world.tracks[30]['v'] == 0.2222, 'le mixeur reste synchronise')
        assert b.world.chans[0]['params'][3] == 0.5, 'parametre applique sur un plugin absent'
        b.world.chans[0]['plugin'] = 'Sytrus'
        pump(lambda: 'x.0' not in b.script.SKIP and b.state()['session']['live'], 'plugin revenu : synchro complete')
        pump(ready, 'reference retablie')

        # changement de preset : beaucoup de parametres d'un coup
        for i in range(30):
            a.world.chans[0]['params'][i] = 0.25
        pump(lambda: b.world.chans[0]['params'][29] == 0.25, 'preset : 30 parametres transmis')
        pump(lambda: any('Preset chang' in m.get('text', '') for m in b.state()['session']['chat']),
             'preset : les autres sont prevenus')

        # stylo
        b.act('baton_req')
        pump(lambda: any(p['asks'] for p in a.state()['session']['peers']), 'A voit la demande de stylo')
        bid = b.state()['session']['id']
        a.act('baton_give', to=bid)
        pump(lambda: b.state()['session']['holder'] and not a.state()['session']['holder'], 'stylo transmis a B', 12)
        with open(os.path.join(bdir, 'Mon Morceau.flp'), 'ab') as f:
            f.write(b'\x00' * 3)
        pump(lambda: a.state()['session']['file_n'] >= 3 and a.state()['session']['rev']['author'] == 'Bob',
             'B publie, A recoit (envoi distant -> hub -> hote)', 20)
        # le projet republie par B revient chez A avec le sample relie au dossier de A
        refs = flp.sample_refs(os.path.join(adir, 'Mon Morceau.flp'))
        assert any(os.path.normcase(pth) == os.path.normcase(os.path.join(adir, 'kick été.wav')) for _, pth in refs), refs

        b.act('leave')
        pump(lambda: len(a.state()['session']['peers']) == 1 and a.state()['session']['holder'],
             'depart de B : le stylo revient a A')
        print('\nTOUS LES TESTS PASSENT')
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
