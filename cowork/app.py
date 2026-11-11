"""Application compagnon FL Cowork.

Relie le script FL Studio (TCP local) au hub de session (TLS-PSK), synchronise
les fichiers du projet et sert l'interface (page web locale).
"""
import asyncio
import collections
import getpass
import hashlib
import json
import os
import secrets
import shutil
import time
import zlib
from urllib.parse import parse_qs, urlsplit

from . import env, flp, midi, net, upnp
from .hub import Hub, TRANSIENT

FLUSH = 0.03          # fenetre de regroupement des ops sortantes (s)
WIN_NAMES = {0: 'Mixeur', 1: 'Channel rack', 2: 'Playlist', 3: 'Piano roll', 4: 'Navigateur', 6: 'Plugin'}


def safe_name(name):
    name = os.path.basename(str(name).replace('\\', '/'))
    return ''.join(c for c in name if c not in '<>:"/\\|?*' and ord(c) >= 32) or 'fichier'


class Session:
    def __init__(self, role, key, port):
        self.role = role
        self.key = key
        self.port = port
        self.hub = None
        self.reader = None
        self.writer = None
        self.id = None
        self.project = ''
        self.peers = {}
        self.rev = None
        self.baton = None
        self.dir = ''
        self.flp = ''
        self.local_n = 0       # revision chargee dans FL
        self.file_n = 0        # revision presente sur le disque
        self.load_pending = 0
        self.known_mtime = None
        self.seen_mtime = None
        self.pub_mtime = None
        self.local_dirty = False
        self.hubops = {}
        self.pending = {}
        self.sent_at = {}
        self.fights = {}
        self.fwd_at = {}
        self.muted = set()
        self.outbox = {}
        self.chat = []
        self.waiting = {}
        self.xfer = None
        self.live = False
        self.why = 'Connexion...'
        self.baton_reqs = {}
        self.codes = {}
        self.publishing = False
        self.fetching = False
        self.tasks = []
        self.shacache = {}
        self.sample_src = {}
        self.lost = ()
        self.warned = set()
        self.burst_at = {}
        self.diffs = []


class App:
    def __init__(self):
        self.cfg = {'name': getpass.getuser(), 'follow': False, 'autoload': True}
        self.cfg.update(env.load_json(env.CONFIG, {}))
        self.token = secrets.token_urlsafe(12)
        self.script = None
        self.sc = {'title': '', 'fp': None, 'sig': None, 'pres': {}}
        self.fp_waiters = []
        self.sess = None
        self.notice = ''
        self.last_ui = time.time()
        self.ui_port = 0
        self.quit = asyncio.Event()
        self.sent_cfg = None
        self.env_cache = (0, {})
        self.loop = None
        self.midi = midi.MidiLink(env.MIDI_BUS, self._midi_rx)
        self.midi_rx_t = 0.0
        self.title_cache = (0.0, '')

    # ------------------------------------------------------------ demarrage
    async def run(self, open_ui=True):
        os.makedirs(env.BLOBS, exist_ok=True)
        self.loop = asyncio.get_running_loop()
        try:
            bridge = await asyncio.start_server(self.on_script, '127.0.0.1', net.BRIDGE_PORT)
        except OSError:
            return          # une autre instance est deja lancee
        http = await asyncio.start_server(self.on_http, '127.0.0.1', 0)
        self.ui_port = http.sockets[0].getsockname()[1]
        url = 'http://127.0.0.1:%d/?t=%s' % (self.ui_port, self.token)
        env.save_json(env.RUNTIME, {'url': url, 'pid': os.getpid()})
        ticker = asyncio.ensure_future(self.ticker())
        flusher = asyncio.ensure_future(self.flusher())
        await self.quit.wait()
        ticker.cancel()
        flusher.cancel()
        await self.leave()
        self.midi.close()
        bridge.close()
        http.close()
        try:
            os.remove(env.RUNTIME)
        except OSError:
            pass

    def say(self, text):
        s = self.sess
        if s:
            s.chat.append({'sys': 1, 'text': text, 'time': time.time()})
            del s.chat[:-200]
        else:
            self.notice = text

    # --------------------------------------------------------- script FL
    def ssend(self, obj):
        if self.script == 'midi':
            self.midi.send(obj)
        elif self.script:
            try:
                self.script.write((json.dumps(obj, separators=(',', ':')) + '\n').encode('utf-8'))
            except Exception:
                pass

    def _midi_rx(self, msg):
        # appele depuis un thread systeme WinMM
        try:
            self.loop.call_soon_threadsafe(self.on_midi_msg, msg)
        except RuntimeError:
            pass

    def on_midi_msg(self, msg):
        self.midi_rx_t = time.time()
        if self.script is None:
            self.script = 'midi'
            self.sc = {'title': '', 'fp': None, 'sig': None, 'pres': {}}
            self.sent_cfg = None
        if self.script == 'midi':
            self.on_script_msg(msg)

    def midi_upkeep(self):
        """(chaque seconde) ouvre le port, envoie le battement, detecte la perte du script."""
        if os.environ.get('FLCOWORK_NO_MIDI'):
            return
        if not self.midi.opened:
            try:
                self.midi.open()
            except OSError:
                return
        if self.midi.opened:
            self.midi.send({'t': 'ping'})
        if self.script == 'midi' and time.time() - self.midi_rx_t > 4:
            self.script = None
            self.sc = {'title': '', 'fp': None, 'sig': None, 'pres': {}}
            self.update_live()

    async def on_script(self, reader, writer):
        """Liaison TCP locale : utilisee par les tests (le vrai FL passe par le MIDI)."""
        if self.script:
            # un seul script a la fois (FL peut l'attacher a plusieurs ports) : le premier reste
            writer.close()
            return
        self.script = writer
        self.sc = {'title': '', 'fp': None, 'sig': None, 'pres': {}}
        self.sent_cfg = None
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode('utf-8'))
                except ValueError:
                    continue
                self.on_script_msg(msg)
        except (ConnectionError, OSError, asyncio.LimitOverrunError, ValueError):
            pass
        finally:
            if self.script is writer:
                self.script = None
                self.sc = {'title': '', 'fp': None, 'sig': None, 'pres': {}}
                self.update_live()
            writer.close()

    def on_script_msg(self, msg):
        t = msg.get('t')
        s = self.sess
        if t == 'ops':
            if s and s.live:
                for k, v in msg.get('o', ()):
                    if k not in s.muted:
                        if k in TRANSIENT:
                            s.outbox.pop(k, None)
                        s.outbox[k] = v
        elif t == 'struct':
            raw = msg.get('fp')
            self.sc['sig'] = raw if isinstance(raw, dict) else None
            self.sc['fp'] = hashlib.md5(json.dumps(raw, sort_keys=True).encode('utf-8')).hexdigest()[:16] if raw else None
            for f in self.fp_waiters:
                if not f.done():
                    f.set_result(self.sc['fp'])
            self.fp_waiters = []
            self.sync_fp()
            self.update_live()
        elif t == 'burst':
            self.on_burst(msg)
        elif t in ('hello', 'pres', 'loaded', 'k'):
            if t == 'hello':
                self.sent_cfg = None
            self.sc['title'] = msg.get('title', self.sc['title'])
            if t == 'pres':
                self.sc['pres'] = msg
            if t == 'loaded':
                self.sc['fp'] = None
                self.sc['sig'] = None
            if s and s.load_pending and self.title_ok() and t in ('hello', 'loaded', 'k'):
                s.local_n = s.load_pending
                s.load_pending = 0
            self.update_live()
            self.send_pres()

    def title_ok(self):
        s = self.sess
        if not s or not s.flp:
            return False
        stem = os.path.splitext(os.path.basename(s.flp))[0].lower()
        return stem in self.project_title().lower()

    def project_title(self):
        """Nom du projet ouvert dans FL : lu sur la fenetre de FL (les tests le simulent via le script)."""
        if os.environ.get('FLCOWORK_NO_MIDI'):
            return self.sc.get('title') or ''
        now = time.time()
        if now - self.title_cache[0] > 0.8:
            self.title_cache = (now, env.fl_window_title())
        return self.title_cache[1]

    def send_pres(self):
        s = self.sess
        if not s or not s.writer:
            return
        p = self.sc.get('pres') or {}
        self.hsend({'t': 'pres', 'p': {
            'fl': bool(self.script), 'live': s.live, 'n': s.local_n,
            'win': p.get('win', -1), 'pat': p.get('pat', 0), 'play': p.get('play', 0)}})

    def sync_fp(self):
        """Le detenteur du stylo fait reference pour la structure du projet."""
        s = self.sess
        return      # synchro en direct retiree : la structure voyage avec le projet
        if not (s and s.rev and s.baton == s.id and self.sc['fp'] and s.local_n == s.rev['n']
                and self.title_ok() and self.sc['fp'] != s.rev.get('fp')):
            return
        clean = not (self.sc.get('pres') or {}).get('dirty')
        if s.rev.get('fp') is None or clean:
            self.hsend({'t': 'fp', 'n': s.rev['n'], 'fp': self.sc['fp'], 'sig': self.sc['sig']})

    def update_live(self):
        s = self.sess
        if not s:
            if self.script and self.sent_cfg != (False, False, ()):
                self.sent_cfg = (False, False, ())
                self.ssend({'t': 'cfg', 'live': False, 'follow': False})
            return
        why = ''
        if not s.writer:
            why = 'Connexion à la session...'
        elif not self.script:
            why = "FL Studio n'est pas connecté"
        elif not s.rev:
            why = 'En attente du projet'
        elif s.local_n != s.rev['n']:
            why = 'Nouvelle version du projet à charger'
        elif not self.title_ok():
            why = 'Ouvrez le projet de la session dans FL Studio'
        skip = []
        s.diffs = []
        live = not why
        was = s.live
        s.live, s.why = live, why
        cfg = (False, False, ())      # le script n'echange plus rien en direct
        if self.script and cfg != self.sent_cfg:
            self.sent_cfg = cfg
            self.ssend({'t': 'cfg', 'live': False, 'follow': False, 'skip': []})
        if live != was:
            self.send_pres()

    @staticmethod
    def plugin_diff(ref, loc):
        """Compare la structure de reference (detenteur du stylo) a la structure locale.

        Renvoie (meme forme, emplacements a ne pas synchroniser, plugins manquants ici,
        descriptions lisibles). Un plugin absent ou different ne bloque pas la session :
        seuls ses parametres sont exclus de la synchro.
        """
        if not ref or not loc:
            return False, [], [], []
        if len(ref['ch']) != len(loc['ch']) or ref['tc'] != loc['tc']:
            return False, [], [], []
        skip, lacking, text = [], [], []
        for g, (a, b) in enumerate(zip(ref['ch'], loc['ch'])):
            if a != b:
                skip.append('x.%d' % g)
                if a not in ('-', '?'):
                    lacking.append(a)
                    text.append('%s (canal %d)' % (a, g + 1))
        for k in sorted(set(ref['fx']) | set(loc['fx'])):
            a, b = ref['fx'].get(k), loc['fx'].get(k)
            if a != b:
                skip.append('y.' + k)
                tr, sl = k.split('.')
                if a and a != '?':
                    lacking.append(a)
                    text.append('%s (mixeur piste %s, slot %d)' % (a, tr, int(sl) + 1))
                else:
                    text.append('%s en plus (mixeur piste %s, slot %d)' % (b, tr, int(sl) + 1))
        return True, skip, sorted(set(lacking)), text

    def warn_plugins(self, names, loaded):
        """Previent (une fois par version) que des plugins du projet manquent sur cette machine."""
        s = self.sess
        key = (s.rev['n'] if s.rev else 0, tuple(names))
        if not names or key in s.warned:
            return
        s.warned.add(key)
        lst = ', '.join(names)
        self.say('Plugin(s) absent(s) de votre FL Studio : %s. Non synchronisés, le reste fonctionne.' % lst)
        self.hsend({'t': 'chat', 'text': '⚠ Il me manque : %s (non synchronisé chez moi).' % lst})
        if not os.environ.get('FLCOWORK_NO_DIALOG'):
            env.message_box(
                'Ce projet utilise des plugins absents de votre FL Studio :\n\n    %s\n\n'
                'Le projet %s quand même. Ces instruments ou effets resteront muets chez vous et '
                'leurs réglages ne seront pas synchronisés ; tout le reste continue de fonctionner.\n\n'
                'Installez-les puis rechargez la version pour les récupérer.'
                % ('\n    '.join(names), "s'est ouvert" if loaded else "va s'ouvrir"))

    def check_plugins(self):
        """Avant chargement : compare les plugins du projet a ceux installes ici."""
        s = self.sess
        sig = s.rev.get('sig') if s and s.rev else None
        if not sig or s.rev['author'] == s.id:
            return
        have = env.installed_plugins()
        names = set(sig['ch']) | set(sig['fx'].values())
        self.warn_plugins(sorted(n for n in names if n not in ('-', '?', '') and n.lower() not in have), loaded=False)

    def on_burst(self, msg):
        """Beaucoup de parametres d'un plugin ont change d'un coup : preset charge."""
        s = self.sess
        if not s or not s.live:
            return
        loc = str(msg.get('loc', ''))
        now = time.time()
        if now - s.burst_at.get(loc, 0) < 15:
            return
        s.burst_at[loc] = now
        sig = self.sc.get('sig') or {'ch': [], 'fx': {}}
        a = loc.split('.')
        try:
            name = sig['ch'][int(a[1])] if a[0] == 'x' else sig['fx']['.'.join(a[1:])]
            where = 'canal %d' % (int(a[1]) + 1) if a[0] == 'x' else 'mixeur piste %s' % a[1]
        except (IndexError, KeyError, ValueError):
            name, where = 'un plugin', ''
        self.hsend({'t': 'chat', 'text': 'Preset changé sur %s (%s) : réglages synchronisés ; le contenu interne '
                    '(tables d\'ondes, samples, modulations) suivra à la prochaine publication.' % (name, where)})
        if s.baton == s.id:
            self.say('Astuce : Ctrl+S pour envoyer le preset complet aux autres.')

    async def ask_fp(self):
        if not self.script:
            return self.sc['fp']
        f = asyncio.get_running_loop().create_future()
        self.fp_waiters.append(f)
        self.ssend({'t': 'fp?'})
        try:
            return await asyncio.wait_for(f, 2.0)
        except asyncio.TimeoutError:
            return self.sc['fp']

    # ------------------------------------------------------------- session
    def hsend(self, obj, data=b''):
        s = self.sess
        if s and s.writer:
            try:
                s.writer.write(net.pack(obj, data))
            except Exception:
                pass

    async def host(self, src, name=''):
        if self.sess:
            raise ValueError('Une session est déjà en cours.')
        if not src:
            src = env.empty_template()
            stem = safe_name(name.strip()) if name.strip() else 'Cowork'
        else:
            stem = os.path.splitext(os.path.basename(src))[0]
        if not src or not os.path.isfile(src):
            raise ValueError('Projet introuvable : %s' % src)
        key = net.new_key()
        sdir = os.path.join(env.sessions_root(), '%s-%s' % (safe_name(stem), secrets.token_hex(3)))
        os.makedirs(sdir, exist_ok=True)
        dst = os.path.join(sdir, safe_name(stem) + '.flp')
        shutil.copy2(src, dst)
        hub = Hub(key, env.BLOBS, project=stem)
        await hub.start()
        s = Session('host', key, hub.port)
        s.hub, s.dir, s.flp, s.project = hub, sdir, dst, stem
        s.src_dir = os.path.dirname(os.path.abspath(src))
        ip = net.lan_ip()
        s.codes = {'lan': net.make_code(ip, hub.port, key)}
        vpn = net.vpn_ips()
        if vpn:
            s.codes['vpn'] = net.make_code(vpn[0], hub.port, key)
        self.sess = s
        try:
            await self.connect('127.0.0.1')
        except Exception:
            await self.leave()
            raise
        s.tasks.append(asyncio.ensure_future(self.open_wan(ip)))
        await self.publish()

    async def open_wan(self, ip):
        s = self.sess
        if os.environ.get('FLCOWORK_NO_UPNP'):
            return
        pub = await asyncio.get_running_loop().run_in_executor(None, upnp.map_port, ip, s.port)
        if pub and self.sess is s:
            s.codes['wan'] = net.make_code(pub, s.port, s.key)

    async def join(self, code):
        if self.sess:
            raise ValueError('Une session est déjà en cours.')
        try:
            ip, port, key = net.parse_code(code)
        except Exception:
            raise ValueError('Code de session invalide.')
        s = Session('guest', key, port)
        self.sess = s
        try:
            await self.connect(ip)
        except Exception:
            self.sess = None
            raise ValueError("Impossible de joindre l'hôte (%s:%d). Vérifiez le code et le réseau." % (ip, port))

    async def connect(self, ip):
        s = self.sess
        ctx = net.psk_context(False, s.key)
        s.reader, s.writer = await asyncio.wait_for(
            asyncio.open_connection(ip, s.port, ssl=ctx, server_hostname=''), 8)
        self.hsend({'t': 'hello', 'name': self.cfg['name'], 'v': 1})
        msg, _ = await asyncio.wait_for(net.read_frame(s.reader), 8)
        if msg.get('t') != 'welcome':
            raise ValueError('reponse inattendue')
        s.id = msg['id']
        s.project = msg.get('project') or s.project
        s.peers = {p['id']: p for p in msg['peers']}
        s.baton = msg.get('baton')
        s.muted = set(msg.get('muted', ()))
        s.hubops = {k: v for k, v, _ in msg.get('ops', ())}
        if not s.dir:
            tag = hashlib.sha1(s.key).hexdigest()[:6]
            s.dir = os.path.join(env.sessions_root(), '%s-%s' % (safe_name(s.project or 'session'), tag))
            os.makedirs(s.dir, exist_ok=True)
        s.tasks.append(asyncio.ensure_future(self.hub_loop(s)))
        self.say('Session rejointe.' if s.role == 'guest' else 'Session créée.')
        if msg.get('rev'):
            self.on_rev(msg['rev'])
        self.update_live()

    async def leave(self, reason=''):
        s = self.sess
        if not s:
            return
        self.sess = None
        for t in s.tasks:
            t.cancel()
        if s.writer:
            s.writer.close()
        if s.hub:
            await s.hub.stop()
            if s.codes.get('wan') and not os.environ.get('FLCOWORK_NO_UPNP'):
                # referme le port ouvert sur la box pour cette session
                try:
                    await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                        None, upnp.unmap_port, net.lan_ip(), s.port), 8)
                except Exception:
                    pass
        for f in s.waiting.values():
            if not f.done():
                f.set_result(False)
        self.notice = reason
        self.update_live()

    async def hub_loop(self, s):
        try:
            while True:
                msg, data = await net.read_frame(s.reader)
                self.on_hub(s, msg, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if self.sess is s:
            s.tasks = [t for t in s.tasks if t is not asyncio.current_task()]
            await self.leave('Connexion à la session perdue.')

    def on_hub(self, s, msg, data):
        t = msg.get('t')
        if t == 'ops':
            self.on_ops(s, msg)
        elif t == 'pres':
            if msg['id'] in s.peers:
                s.peers[msg['id']]['pres'] = msg.get('p') or {}
        elif t == 'join':
            p = msg['peer']
            if p['id'] not in s.peers and p['id'] != s.id:
                self.say('%s a rejoint la session.' % p['name'])
            s.peers[p['id']] = p
        elif t == 'leave':
            p = s.peers.pop(msg['id'], None)
            s.baton_reqs.pop(msg['id'], None)
            if p:
                self.say('%s a quitté la session.' % p['name'])
        elif t == 'chat':
            s.chat.append(msg)
            del s.chat[:-200]
        elif t == 'baton':
            s.baton = msg.get('holder')
            s.baton_reqs.clear()
            who = s.peers.get(s.baton, {}).get('name', '?')
            self.say('Vous avez le stylo.' if s.baton == s.id else '%s a le stylo.' % who)
            self.update_live()
            self.sync_fp()
        elif t == 'baton_req':
            if s.baton == s.id and msg['from'] != s.id:
                s.baton_reqs[msg['from']] = msg.get('name', '?')
                self.ssend({'t': 'notify', 'msg': 'FL Cowork : %s demande le stylo' % msg.get('name', '?')})
        elif t == 'mute':
            s.muted.add(msg['k'])
            s.hubops.pop(msg['k'], None)
            s.pending.pop(msg['k'], None)
        elif t == 'rev':
            self.on_rev(msg['rev'])
        elif t == 'need':
            s.tasks.append(asyncio.ensure_future(self.upload(s, msg['shas'])))
        elif t == 'blob':
            self.on_blob(s, msg, data)
        elif t == 'stale':
            if not s.fetching and s.rev and s.file_n != s.rev['n'] and s.rev.get('author') != s.id:
                s.tasks.append(asyncio.ensure_future(self.fetch(s)))
        elif t == 'error':
            self.say(msg.get('msg', 'Erreur'))

    def on_ops(self, s, msg):
        mine = msg.get('from') == s.id
        now = time.time()
        fwd = []
        for k, v, _seq in msg.get('o', ()):
            if k in s.muted:
                continue
            if k not in TRANSIENT:
                s.hubops[k] = v
            if mine:
                n = s.pending.get(k, 0) - 1
                if n > 0:
                    s.pending[k] = n
                else:
                    s.pending.pop(k, None)
                    if now - s.fwd_at.get(k, 0) < 2.0 and k not in TRANSIENT:
                        # une valeur distante a croise la mienne en route vers le script :
                        # le hub a tranche pour la mienne, on la reaffirme localement
                        fwd.append([k, v])
                continue
            if s.pending.get(k):
                continue          # mon operation plus recente gagnera
            if now - s.sent_at.get(k, 0) < 1.0 and k not in TRANSIENT:
                cnt, t0 = s.fights.get(k, (0, now))
                if now - t0 > 5:
                    cnt, t0 = 0, now
                s.fights[k] = (cnt + 1, t0)
                if cnt + 1 >= 4:  # valeur automatisee des deux cotes : on arrete de la synchroniser
                    self.hsend({'t': 'mute', 'k': k})
                    continue
            s.fwd_at[k] = now
            fwd.append([k, v])
        if fwd and s.live:
            self.ssend({'t': 'ops', 'o': fwd})

    async def flusher(self):
        while True:
            await asyncio.sleep(FLUSH)
            s = self.sess
            if s and s.outbox and s.writer:
                o = list(s.outbox.items())
                s.outbox.clear()
                now = time.time()
                for k, _ in o:
                    s.pending[k] = s.pending.get(k, 0) + 1
                    s.sent_at[k] = now
                self.hsend({'t': 'ops', 'o': o})

    # ------------------------------------------------- revisions du projet
    def on_rev(self, rev):
        s = self.sess
        old = s.rev['n'] if s.rev else 0
        s.rev = rev
        if rev['n'] != old:
            s.hubops.clear()
            s.pending.clear()
            s.fights.clear()
            s.muted.clear()
            if rev['author'] == s.id:
                try:
                    os.replace(os.path.join(s.dir, '.base.new'), os.path.join(s.dir, '.base.flp'))
                except OSError:
                    pass
                s.local_n = s.file_n = rev['n']
                s.local_dirty = False
                s.known_mtime = s.pub_mtime
                self.say('Version %d publiée.' % rev['n'])
                if not self.title_ok():
                    self.open_in_fl()
            else:
                self.say('%s a publié la version %d.' % (rev.get('author_name', '?'), rev['n']))
                if not s.fetching:
                    s.tasks.append(asyncio.ensure_future(self.fetch(s)))
        self.check_plugins()
        self.update_live()

    def _sha(self, s, path):
        st = os.stat(path)
        key = (path, st.st_size, st.st_mtime_ns)
        if key not in s.shacache:
            s.shacache[key] = net.sha_file(path)
        return s.shacache[key]

    def _prepare(self, s):
        """(thread) Rassemble les samples, calcule le manifeste, alimente le cache de blobs."""
        _, inst, user = env.fl_paths()
        samples, lost = [], []
        for raw, p in flp.sample_refs(s.flp, user, inst):
            name = os.path.basename(p)
            if not os.path.isfile(p):
                lost.append(name)
                continue
            if os.path.dirname(p).lower() == s.dir.lower():
                samples.append([raw, name])
                continue
            dst = os.path.join(s.dir, name)
            src_key = p.lower()
            if os.path.exists(dst) and s.sample_src.get(name.lower(), src_key) != src_key:
                # deux samples differents portent le meme nom : on en renomme un
                stem, ext = os.path.splitext(name)
                name = '%s-%s%s' % (stem, hashlib.sha1(src_key.encode('utf-8')).hexdigest()[:6], ext)
                dst = os.path.join(s.dir, name)
            try:
                st = os.stat(p)
                if not os.path.exists(dst) or os.path.getsize(dst) != st.st_size \
                        or int(os.path.getmtime(dst)) != int(st.st_mtime):
                    shutil.copy2(p, dst)
                s.sample_src[name.lower()] = src_key
                samples.append([raw, name])
            except OSError:
                lost.append(name)
        mtime = os.stat(s.flp).st_mtime_ns
        shutil.copyfile(s.flp, os.path.join(s.dir, '.base.new'))   # deviendra la reference si le serveur accepte
        files = []
        for name in sorted(os.listdir(s.dir)):
            path = os.path.join(s.dir, name)
            if not os.path.isfile(path) or name.startswith('.') or name.endswith(('.part', '.tmp')):
                continue
            sha = self._sha(s, path)
            blob = os.path.join(env.BLOBS, sha)
            if not os.path.exists(blob):
                shutil.copyfile(path, blob + '.tmp')
                os.replace(blob + '.tmp', blob)
            files.append([name, os.path.getsize(path), sha])
        return files, mtime, samples, lost

    async def publish(self):
        s = self.sess
        if not s or s.publishing or not s.flp:
            return
        if s.rev and s.file_n != s.rev['n'] and s.rev.get('author') != s.id:
            # une version plus recente existe : on la recoit et on y fusionne ce travail, puis on publie
            if not s.fetching:
                s.tasks.append(asyncio.ensure_future(self.fetch(s)))
            return
        s.publishing = True
        try:
            fp = await self.ask_fp() if self.title_ok() else None
            files, mtime, samples, lost = await asyncio.get_running_loop().run_in_executor(None, self._prepare, s)
            s.pub_mtime = mtime
            if lost and tuple(lost) != s.lost:
                self.say('Sample(s) introuvable(s) sur votre disque, non partagé(s) : %s' % ', '.join(lost))
            s.lost = tuple(lost)
            self.hsend({'t': 'publish', 'manifest': {
                'flp': os.path.basename(s.flp), 'files': files, 'fp': fp, 'parent': s.file_n,
                'sig': self.sc.get('sig') if fp else None, 'samples': samples}})
        except Exception as e:
            self.say('Publication impossible : %s' % e)
        finally:
            s.publishing = False

    async def upload(self, s, shas):
        total = sum(os.path.getsize(os.path.join(env.BLOBS, h)) for h in shas)
        done = 0
        s.xfer = {'label': 'Envoi', 'done': 0, 'total': total}
        try:
            for sha in shas:
                path = os.path.join(env.BLOBS, sha)
                size = os.path.getsize(path)
                off = 0
                with open(path, 'rb') as f:
                    while True:
                        chunk = f.read(net.CHUNK)
                        last = off + len(chunk) >= size
                        self.hsend({'t': 'blob', 'sha': sha, 'off': off, 'last': int(last)},
                                   zlib.compress(chunk, 1))
                        await s.writer.drain()
                        off += len(chunk)
                        done += len(chunk)
                        s.xfer['done'] = done
                        if last:
                            break
        finally:
            s.xfer = None

    def on_blob(self, s, msg, data):
        sha = msg.get('sha', '')
        fut = s.waiting.get(sha)
        if fut is None or not sha.isalnum():
            return
        if msg.get('missing'):
            fut.set_result(False)
            return
        part = os.path.join(env.BLOBS, sha + '.part')
        with open(part, 'ab' if msg.get('off') else 'wb') as f:
            f.write(zlib.decompress(data))
        if s.xfer:
            s.xfer['done'] += net.CHUNK if not msg.get('last') else 0
        if msg.get('last'):
            if net.sha_file(part) == sha:
                os.replace(part, os.path.join(env.BLOBS, sha))
                fut.set_result(True)
            else:
                os.remove(part)
                fut.set_result(False)

    async def fetch(self, s):
        """Telecharge la revision courante dans le dossier de session puis la charge."""
        s.fetching = True
        loop = asyncio.get_running_loop()
        try:
            while self.sess is s and s.rev and s.file_n != s.rev['n'] and s.rev['author'] != s.id:
                rev = s.rev
                todo = []
                for name, size, sha in rev['files']:
                    dst = os.path.join(s.dir, safe_name(name))
                    if os.path.exists(dst) and os.path.getsize(dst) == size and \
                            await loop.run_in_executor(None, self._sha, s, dst) == sha:
                        continue
                    todo.append((dst, size, sha))
                missing = [t for t in todo if not os.path.exists(os.path.join(env.BLOBS, t[2]))]
                if missing:
                    s.xfer = {'label': 'Réception', 'done': 0, 'total': sum(t[1] for t in missing)}
                ok = True
                for dst, size, sha in todo:
                    blob = os.path.join(env.BLOBS, sha)
                    if not os.path.exists(blob):
                        fut = loop.create_future()
                        s.waiting[sha] = fut
                        self.hsend({'t': 'get', 'sha': sha})
                        got = await fut
                        s.waiting.pop(sha, None)
                        if not got:
                            ok = False
                            continue
                s.xfer = None
                # tout est telecharge : on fige maintenant le travail local, juste avant d'ecraser le projet
                mine, local = await self.snapshot_local(s)
                for dst, size, sha in todo:
                    blob = os.path.join(env.BLOBS, sha)
                    if os.path.exists(blob):
                        await loop.run_in_executor(None, shutil.copyfile, blob, dst)
                if not ok:
                    self.say('Certains fichiers du projet sont introuvables.')
                s.flp = os.path.join(s.dir, safe_name(rev['flp']))
                # les chemins de samples du projet pointent vers la machine de l'auteur :
                # on les redirige vers les copies recues dans le dossier de session
                mapping = {raw: os.path.join(s.dir, safe_name(name)) for raw, name in rev.get('samples') or ()
                           if os.path.exists(os.path.join(s.dir, safe_name(name)))}
                if mapping:
                    try:
                        n = await loop.run_in_executor(None, flp.rewrite_samples, s.flp, s.flp, mapping)
                        self.say('%d sample(s) reçu(s) et relié(s) au projet.' % n)
                    except (OSError, ValueError) as e:
                        self.say('Samples reçus mais non reliés au projet : %s' % e)
                changed = await loop.run_in_executor(None, self.finish_fetch, s, mine, local)
                s.known_mtime = s.seen_mtime = os.stat(s.flp).st_mtime_ns
                s.file_n = rev['n']
                s.local_dirty = False
                if self.cfg.get('autoload') or s.local_n == 0:
                    self.open_in_fl()
                self.update_live()
                if changed:
                    await self.publish()      # le travail local fusionne repart chez les autres
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.say('Réception du projet impossible : %s' % e)
        finally:
            s.fetching = False
            s.xfer = None

    async def snapshot_local(self, s):
        """Sauvegarde le travail en cours dans FL puis renvoie les octets du projet local
        s'il differe de la derniere version connue (None sinon)."""
        base = os.path.join(s.dir, '.base.flp')
        if not s.file_n or not os.path.exists(base) or not os.path.exists(s.flp):
            return None, None
        if self.script and self.title_ok() and (self.sc.get('pres') or {}).get('dirty'):
            before = os.stat(s.flp).st_mtime_ns
            self.ssend({'t': 'save'})
            for _ in range(60):
                await asyncio.sleep(0.1)
                if os.stat(s.flp).st_mtime_ns != before:
                    await asyncio.sleep(0.3)
                    break

        def read():
            with open(s.flp, 'rb') as f, open(base, 'rb') as g:
                mine, ref = f.read(), g.read()
            if flp.same_content(mine, ref):
                return None, mine
            bk = os.path.join(s.dir, 'Sauvegardes')
            os.makedirs(bk, exist_ok=True)
            with open(os.path.join(bk, time.strftime('local-%Hh%Mm%S.flp')), 'wb') as f:
                f.write(mine)
            return mine, mine
        return await asyncio.get_running_loop().run_in_executor(None, read)

    def finish_fetch(self, s, mine, local=None):
        """(thread) Reference de fusion, fusion du travail local, version de FL."""
        base = os.path.join(s.dir, '.base.flp')
        with open(s.flp, 'rb') as f:
            theirs = f.read()
        data = theirs
        changed = False
        if mine is not None:
            with open(base, 'rb') as f:
                ref = f.read()
            data, r = flp.merge(ref, mine, theirs)
            if r['ok']:
                changed = r['changed']
                if changed:
                    msg = 'Votre travail local a été fusionné avec la nouvelle version'
                    if r['notes'] or r['items']:
                        msg += ' (%d note(s), %d clip(s) de playlist' % (r['notes'], r['items'])
                        msg += ', dont %d décalé(s) sur une autre piste)' % r['moved'] if r['moved'] else ')'
                    if r['conflicts']:
                        msg += ' ; %d réglage(s) modifié(s) des deux côtés : le vôtre a été gardé' % r['conflicts']
                    self.say(msg + '.')
            else:
                self.say("Votre travail local n'a pas pu être fusionné (%s) ; copie dans le dossier "
                         "« Sauvegardes » de la session." % r['why'])
        if local is None:        # premiere reception : reglages personnels neutres (modele vide de FL)
            try:
                with open(env.empty_template(), 'rb') as f:
                    local = f.read()
            except (OSError, TypeError):
                local = None
        if local is not None:
            data = flp.keep_personal(data, local)
        ver = env.fl_version()
        if ver and flp._vtuple(flp.version_of(data)) > flp._vtuple(ver):
            theirs = flp.set_version(theirs, ver)
            data = flp.set_version(data, ver)
        with open(base, 'wb') as f:
            f.write(theirs)
        with open(s.flp, 'wb') as f:
            f.write(data)
        return changed

    def open_in_fl(self):
        s = self.sess
        if not s or not s.flp or not os.path.exists(s.flp):
            return
        s.load_pending = s.file_n or (s.rev['n'] if s.rev else 0)
        if os.environ.get('FLCOWORK_NO_LAUNCH'):
            return
        try:
            os.startfile(s.flp)
            env.dismiss_dialogs()
        except OSError as e:
            self.say("Impossible d'ouvrir FL Studio : %s" % e)

    async def ticker(self):
        """Surveille le .flp de la session (enregistrement = publication) et l'inactivite."""
        while True:
            await asyncio.sleep(1.0)
            self.midi_upkeep()
            s = self.sess
            if s:
                self.update_live()
            if not s:
                if time.time() - self.last_ui > 25:
                    self.quit.set()
                continue
            self.sync_fp()
            try:
                m = os.stat(s.flp).st_mtime_ns if s.flp else None
            except OSError:
                m = None
            if m is not None and m != s.known_mtime and s.known_mtime is not None:
                if m == s.seen_mtime:
                    s.known_mtime = m
                    await self.publish()
                s.seen_mtime = m

    async def give_baton(self, to):
        s = self.sess
        if not s or s.baton != s.id or to not in s.peers:
            return
        if self.script and s.live is not None and (self.sc.get('pres') or {}).get('dirty') and self.title_ok():
            n = s.rev['n'] if s.rev else 0
            self.ssend({'t': 'save'})
            for _ in range(60):
                await asyncio.sleep(0.1)
                if self.sess is not s or (s.rev and s.rev['n'] > n):
                    break
        self.hsend({'t': 'baton_give', 'to': to})

    # ------------------------------------------------------------ interface
    def env_state(self):
        t, v = self.env_cache
        if time.time() - t > 3:
            v = {'script': env.script_installed(), 'midi': env.midi_port_ready(), 'fl_exe': bool(env.fl_paths()[0])}
            self.env_cache = (time.time(), v)
        return v

    def state(self):
        self.last_ui = time.time()
        s = self.sess
        out = {'name': self.cfg['name'], 'follow': self.cfg['follow'], 'autoload': self.cfg['autoload'],
               'fl': bool(self.script), 'fl_title': self.project_title(), 'notice': self.notice,
               'env': self.env_state(), 'session': None}
        if s:
            peers = []
            for p in sorted(s.peers.values(), key=lambda p: p['id']):
                pr = p.get('pres') or {}
                me = p['id'] == s.id
                if me:
                    pr = {'fl': bool(self.script), 'live': s.live, 'n': s.local_n,
                          'win': (self.sc.get('pres') or {}).get('win', -1),
                          'play': (self.sc.get('pres') or {}).get('play', 0)}
                peers.append({'id': p['id'], 'name': p['name'], 'color': p['color'], 'me': me,
                              'holder': p['id'] == s.baton, 'fl': bool(pr.get('fl')),
                              'live': bool(pr.get('live')), 'n': pr.get('n', 0),
                              'where': WIN_NAMES.get(pr.get('win'), ''), 'play': bool(pr.get('play')),
                              'asks': p['id'] in s.baton_reqs})
            out['session'] = {
                'role': s.role, 'project': s.project, 'codes': s.codes, 'port': s.port, 'id': s.id,
                'peers': peers, 'holder': s.baton == s.id, 'live': s.live, 'why': s.why,
                'rev': {'n': s.rev['n'], 'author': s.rev.get('author_name', '')} if s.rev else None,
                'local_n': s.local_n, 'file_n': s.file_n, 'local_dirty': s.local_dirty,
                'xfer': s.xfer, 'chat': s.chat[-80:], 'dir': s.dir, 'muted': len(s.muted), 'diffs': s.diffs,
            }
        return out

    async def act(self, a):
        op = a.get('op')
        s = self.sess
        loop = asyncio.get_running_loop()
        self.notice = ''
        if op == 'name':
            self.cfg['name'] = str(a.get('value') or '').strip()[:32] or self.cfg['name']
            env.save_json(env.CONFIG, self.cfg)
            self.hsend({'t': 'name', 'name': self.cfg['name']})
        elif op == 'set':
            if a.get('key') in ('follow', 'autoload'):
                self.cfg[a['key']] = bool(a.get('value'))
                env.save_json(env.CONFIG, self.cfg)
                self.update_live()
        elif op == 'browse':
            return {'path': await loop.run_in_executor(None, env.pick_flp)}
        elif op == 'host':
            await self.host(a.get('path') or '', str(a.get('name') or ''))
        elif op == 'join':
            await self.join(a.get('code') or '')
        elif op == 'leave':
            await self.leave()
        elif op == 'chat' and s:
            if str(a.get('text', '')).strip():
                self.hsend({'t': 'chat', 'text': str(a['text']).strip()})
        elif op == 'baton_req' and s:
            self.hsend({'t': 'baton_req'})
            self.say('Demande de stylo envoyée.')
        elif op == 'baton_give' and s:
            await self.give_baton(int(a.get('to', 0)))
        elif op == 'publish' and s:
            if self.script and self.title_ok():
                self.ssend({'t': 'save'})
            else:
                await self.publish()
        elif op == 'reload' and s:
            if s.rev and s.file_n != s.rev['n'] and not s.fetching and s.rev['author'] != s.id:
                s.tasks.append(asyncio.ensure_future(self.fetch(s)))
            else:
                self.open_in_fl()
        elif op == 'folder' and s:
            os.startfile(s.dir)
        elif op == 'code' and s and s.role == 'host':
            try:
                return {'code': net.make_code(str(a.get('ip', '')).strip(), s.port, s.key)}
            except OSError:
                raise ValueError('Adresse IP invalide.')
        elif op == 'setup':
            from . import setup
            await loop.run_in_executor(None, setup.install_script)
            if not env.midi_port_ready():
                env.run_elevated('--midi-setup')
            self.env_cache = (0, {})
        elif op == 'quit':
            self.quit.set()
        return {}

    async def on_http(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            method, target, _ = line.decode('latin-1').split(' ', 2)
            headers = {}
            while True:
                h = await reader.readline()
                if h in (b'\r\n', b'\n', b''):
                    break
                k, _, v = h.decode('latin-1').partition(':')
                headers[k.strip().lower()] = v.strip()
            n = int(headers.get('content-length', 0) or 0)
            body = await reader.readexactly(n) if 0 < n < 1_000_000 else b''
            url = urlsplit(target)
            host = headers.get('host', '').split(':')[0]
            status, ctype, payload = 403, 'text/plain', b'forbidden'
            if host in ('127.0.0.1', 'localhost'):
                tok = headers.get('x-token') or (parse_qs(url.query).get('t') or [''])[0]
                good = secrets.compare_digest(tok, self.token)
                if url.path == '/api/state' and good:
                    status, ctype, payload = 200, 'application/json', json.dumps(self.state()).encode()
                elif url.path == '/api/act' and good and method == 'POST':
                    try:
                        res = await self.act(json.loads(body.decode('utf-8') or '{}'))
                        res['ok'] = True
                    except Exception as e:
                        res = {'ok': False, 'error': str(e) or e.__class__.__name__}
                    status, ctype, payload = 200, 'application/json', json.dumps(res).encode()
            writer.write(('HTTP/1.1 %d OK\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                          'Cache-Control: no-store\r\nConnection: close\r\n\r\n'
                          % (status, ctype, len(payload))).encode() + payload)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()


def main(open_ui=True):
    if open_ui:
        from . import gui
        gui.run(App)
        return
    app = App()
    try:
        asyncio.run(app.run(open_ui))
    except KeyboardInterrupt:
        pass
