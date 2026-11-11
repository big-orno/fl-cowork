# name=FL Cowork
# url=https://github.com/
# supportedDevices=FL Cowork
"""FL Cowork - pont temps reel entre FL Studio et l'application FL Cowork.

Tourne dans l'interpreteur Python de FL Studio. Observe l'etat du projet
(mixeur, canaux, step sequencer, patterns, parametres de plugins, tempo),
envoie les changements locaux a l'application compagnon (SysEx MIDI) et
applique les changements recus des autres participants.

Regles de conception :
- jamais de blocage : travail borne par tick (BUDGET) ;
- une cle vue pour la premiere fois sert de reference (pas d'emission) ;
- apres application d'une valeur distante, la valeur relue devient la
  reference, donc pas d'echo.
"""
import json
import time
import traceback
from collections import deque

_LOGGED = {}


def log(text):
    """Diagnostic : visible dans FL Studio, View > Script output (une fois par message)."""
    if text in _LOGGED or len(_LOGGED) > 40:
        return
    _LOGGED[text] = 1
    print('[FL Cowork] ' + text)


import channels
import device
import general
import midi
import mixer
import patterns
import playlist
import plugins
import transport
import ui

FRAME = 480            # octets de charge utile par SysEx
MAXTX = 8              # SysEx emis par tick au maximum
VERSION = 1
BUDGET = 0.0015        # secondes de scan par tick en regime normal
BUDGET_HOT = 0.004     # juste apres une action utilisateur
BUDGET_WARM = 0.008    # premiere passe apres (re)synchronisation
STEPS = 64             # pas du step sequencer synchronises par canal
PCHUNK = 128           # parametres de plugin lus par unite de travail
MAXPARAMS = 4240
BURST = 24             # parametres modifies en une passe = preset charge

_MISSING = object()
S = {}                 # reference : cle -> derniere valeur connue
SKIP = set()           # plugins differents d'un participant a l'autre : non synchronises
PCOUNT = {}            # (index, slot) -> (annonce, reel) nombre de parametres
OUT = []               # changements locaux a envoyer
DEFER = {}             # pattern -> {canal: masque} en attente d'application
ST = {
    'live': False, 'follow': False, 'loading': False, 'pat': -1,
    'boost': 0.0, 'pres': None, 'pres_t': 0.0, 'fp': None, 'walker': None,
    'hot': [], 'focus': None, 'fgen': None, 'play': None, 'passes': 0, 'warm': False,
}


def r4(v):
    return round(v, 4)


def see(k, v):
    if not ST['live']:
        return
    o = S.get(k, _MISSING)
    if o is _MISSING:
        S[k] = v
    elif o != v:
        S[k] = v
        OUT.append((k, v))


# ---------------------------------------------------------------- liaison --
# Le Python de FL Studio interdit sockets et ecriture de fichiers : tout passe
# en SysEx sur le port MIDI virtuel. Trame : F0 7D <sens> <fin> <json ascii> F7
# (sens 'S' = script -> application, 'A' = application -> script ;
#  fin '1' = dernier fragment, '0' = a suivre).
class Link:
    def __init__(self):
        self.up = False
        self.rx = []
        self.parts = []
        self.outq = deque()
        self.last_rx = 0.0
        self.last_tx = 0.0

    def close(self):
        self.up = False
        self.outq.clear()
        ST['live'] = False

    def on_sysex(self, data):
        d = bytes(data)
        if d[:1] == b'\xf0':
            d = d[1:]
        if d[-1:] == b'\xf7':
            d = d[:-1]
        if len(d) < 3 or d[0] != 0x7D or d[1] != 0x41:
            return
        self.parts.append(d[3:])
        if d[2] == 0x31:
            raw = b''.join(self.parts)
            self.parts = []
            self.last_rx = time.perf_counter()
            try:
                self.rx.append(json.loads(raw.decode('ascii')))
            except Exception:
                pass

    def send(self, obj):
        if not self.up:
            return
        raw = json.dumps(obj, separators=(',', ':')).encode('ascii')
        n = len(raw)
        for i in range(0, n, FRAME):
            self.outq.append(bytes((0xF0, 0x7D, 0x53, 0x31 if i + FRAME >= n else 0x30))
                             + raw[i:i + FRAME] + b'\xf7')

    def poll(self, now):
        """Fait avancer la liaison ; renvoie les messages recus."""
        msgs = self.rx
        self.rx = []
        up = self.last_rx > 0 and now - self.last_rx < 4.0
        if up and not self.up:
            self.up = True
            S.clear()
            self.send({'t': 'hello', 'ver': VERSION, 'title': title()})
            ST['pres'] = None
            ST['fp'] = None
        elif self.up and not up:
            self.close()
        if self.up:
            if now - self.last_tx > 1.0:
                self.send({'t': 'k', 'title': title()})
            n = 0
            while self.outq and n < MAXTX:
                device.midiOutSysex(self.outq.popleft())
                n += 1
                self.last_tx = now
        return msgs


LINK = Link()


def title():
    try:
        return ui.getProgTitle()
    except Exception:
        return ''


# ------------------------------------------------------- acces a l'etat ----
MIX = {
    'v': (lambda i: r4(mixer.getTrackVolume(i)), lambda i, v: mixer.setTrackVolume(i, v)),
    'p': (lambda i: r4(mixer.getTrackPan(i)), lambda i, v: mixer.setTrackPan(i, v)),
    'ss': (lambda i: r4(mixer.getTrackStereoSep(i)), lambda i, v: mixer.setTrackStereoSep(i, v)),
    'mu': (lambda i: int(mixer.isTrackMuted(i)), lambda i, v: mixer.muteTrack(i, int(v))),
    'en': (lambda i: int(mixer.isTrackSlotsEnabled(i)), lambda i, v: mixer.enableTrackSlots(i, bool(v))),
    'n': (lambda i: mixer.getTrackName(i), lambda i, v: mixer.setTrackName(i, v)),
    'c': (lambda i: mixer.getTrackColor(i), lambda i, v: mixer.setTrackColor(i, v)),
}
EQ = {
    'eg': (lambda i, b: r4(mixer.getEqGain(i, b)), lambda i, b, v: mixer.setEqGain(i, b, v)),
    'ef': (lambda i, b: r4(mixer.getEqFrequency(i, b)), lambda i, b, v: mixer.setEqFrequency(i, b, v)),
    'eb': (lambda i, b: r4(mixer.getEqBandwidth(i, b)), lambda i, b, v: mixer.setEqBandwidth(i, b, v)),
}
CH = {
    'v': (lambda g: r4(channels.getChannelVolume(g, False, True)),
          lambda g, v: channels.setChannelVolume(g, v, midi.PIM_None, True)),
    'p': (lambda g: r4(channels.getChannelPan(g, True)),
          lambda g, v: channels.setChannelPan(g, v, midi.PIM_None, True)),
    'pi': (lambda g: r4(channels.getChannelPitch(g, 0, True)),
           lambda g, v: channels.setChannelPitch(g, v, 0, midi.PIM_None, True)),
    'mu': (lambda g: int(channels.isChannelMuted(g, True)),
           lambda g, v: channels.muteChannel(g, int(v), True)),
    'fx': (lambda g: channels.getTargetFxTrack(g, True),
           lambda g, v: channels.setTargetFxTrack(g, int(v), True)),
    'n': (lambda g: channels.getChannelName(g, True),
          lambda g, v: channels.setChannelName(g, v, True)),
    'c': (lambda g: channels.getChannelColor(g, True),
          lambda g, v: channels.setChannelColor(g, v, True)),
}
PAT = {
    'n': (lambda n: patterns.getPatternName(n), lambda n, v: patterns.setPatternName(n, v)),
    'c': (lambda n: patterns.getPatternColor(n), lambda n, v: patterns.setPatternColor(n, v)),
}
PLT = {
    'n': (lambda i: playlist.getTrackName(i), lambda i, v: playlist.setTrackName(i, v)),
    'c': (lambda i: playlist.getTrackColor(i), lambda i, v: playlist.setTrackColor(i, v)),
    'mu': (lambda i: int(playlist.isTrackMuted(i)), lambda i, v: playlist.muteTrack(i, int(v))),
}


def get_tempo():
    t = mixer.getCurrentTempo()
    if t > 2000:
        t = t / 1000.0
    return round(t, 3)


def set_tempo(bpm):
    general.processRECEvent(midi.REC_Tempo, int(round(bpm * 1000)),
                            midi.REC_Control | midi.REC_UpdateControl)


def get_route(i, d):
    if mixer.getRouteSendActive(i, d):
        return r4(mixer.getRouteToLevel(i, d))
    return -1


def set_route(i, d, v):
    on = v >= 0
    if bool(mixer.getRouteSendActive(i, d)) != on:
        mixer.setRouteTo(i, d, on)
        mixer.afterRoutingChanged()
    if on:
        mixer.setRouteToLevel(i, d, v)


def get_grid(g):
    m = 0
    gb = channels.getGridBit
    for s in range(STEPS):
        if gb(g, s, True):
            m |= 1 << s
    return m


def set_grid(g, mask):
    cur = get_grid(g)
    diff = cur ^ mask
    s = 0
    while diff:
        if diff & 1:
            channels.setGridBit(g, s, bool((mask >> s) & 1), True)
        diff >>= 1
        s += 1


# ------------------------------------------------------------- scanners ----
def scan_mixer(i):
    p = 'm.%d.' % i
    for f, (g, _) in MIX.items():
        see(p + f, g(i))
    for b in range(3):
        for f, (g, _) in EQ.items():
            see('%s%s.%d' % (p, f, b), g(i, b))


def scan_routes(i, tc):
    p = 'm.%d.r.' % i
    for d in range(tc):
        if d != i:
            see(p + str(d), get_route(i, d))


def scan_channel(g):
    p = 'c.%d.' % g
    for f, (get, _) in CH.items():
        see(p + f, get(g))


def scan_grid(g):
    see('g.%d.%d' % (ST['pat'], g), get_grid(g))


def scan_params(prefix, a, b, start, count):
    """Lit count parametres d'un plugin a partir de start."""
    gv = plugins.getParamValue
    if b is None:
        for p in range(start, start + count):
            see('%s%d' % (prefix, p), r4(gv(p, a, -1, True)))
    else:
        for p in range(start, start + count):
            see('%s%d' % (prefix, p), r4(gv(p, a, b)))


def real_count(a, b, n):
    """Nombre de parametres reellement exposes (les VST en annoncent 4096 + 128 CC MIDI).

    Recherche dichotomique du dernier parametre nomme ; resultat mis en cache.
    """
    key = (a, b)
    c = PCOUNT.get(key)
    if c is not None and c[0] == n:
        return c[1]
    if n <= 512:
        real = n
    else:
        top = min(n, 4096)
        if b is None:
            name = lambda p: plugins.getParamName(p, a, -1, True)
        else:
            name = lambda p: plugins.getParamName(p, a, b)
        try:
            if name(top - 1):
                real = top
            else:
                lo, hi = 0, top - 1          # name(hi) vide ; on cherche le premier vide stable
                while lo < hi:
                    mid = (lo + hi) // 2
                    if name(mid) or name(min(mid + 8, top - 1)) or name(min(mid + 64, top - 1)):
                        lo = mid + 1
                    else:
                        hi = mid
                real = min(top, lo + 64)
        except Exception:
            real = top
    PCOUNT[key] = (n, real)
    return real


def plugin_units(a, b):
    """Generateur : scanne un plugin par morceaux de PCHUNK parametres."""
    if b is None:
        loc = 'x.%d' % a
        if loc in SKIP or not plugins.isValid(a, -1, True):
            return
        n = plugins.getParamCount(a, -1, True)
    else:
        loc = 'y.%d.%d' % (a, b)
        if loc in SKIP or not plugins.isValid(a, b):
            return
        n = plugins.getParamCount(a, b)
    prefix = loc + '.'
    n = real_count(a, b, min(n, MAXPARAMS))
    burst = 0
    for st in range(0, n, PCHUNK):
        before = len(OUT)
        scan_params(prefix, a, b, st, min(PCHUNK, n - st))
        burst += len(OUT) - before
        yield
    if burst >= BURST:
        # beaucoup de parametres d'un coup : changement de preset probable
        LINK.send({'t': 'burst', 'loc': loc, 'n': burst})


def scan_global():
    pat = patterns.patternNumber()
    if pat != ST['pat']:
        ST['pat'] = pat
        todo = DEFER.pop(pat, None)
        if todo and ST['live']:
            for g, mask in todo.items():
                try:
                    set_grid(g, mask)
                    S['g.%d.%d' % (pat, g)] = get_grid(g)
                except Exception:
                    pass
        if ST['live']:
            # reference immediate du nouveau pattern : le premier pas pose ne doit pas etre perdu
            for g in range(channels.channelCount(True)):
                k = 'g.%d.%d' % (pat, g)
                if k not in S:
                    S[k] = get_grid(g)
    see('t', get_tempo())
    play = int(transport.isPlaying())
    if play != ST['play']:
        first = ST['play'] is None
        ST['play'] = play
        if ST['live'] and ST['follow'] and not first:
            if play:
                OUT.append(('ts', transport.getSongPos(2)))
            OUT.append(('tp', play))


def focused_plugin():
    """(canal, None) ou (piste, slot) du plugin au premier plan, sinon None."""
    try:
        if not ui.getFocusedPluginName():
            return None
        fid = ui.getFocusedFormID()
        if fid >= 65536:
            return (fid >> 22, (fid >> 16) & 63)
        if 0 <= fid < channels.channelCount(True):
            return (fid, None)
    except Exception:
        pass
    return None


def struct_sig():
    """Structure du projet : plugin de chaque canal, nombre de pistes, effets du mixeur."""
    ch = []
    for g in range(channels.channelCount(True)):
        try:
            ch.append(plugins.getPluginName(g, -1, False, True) if plugins.isValid(g, -1, True) else '-')
        except Exception:
            ch.append('?')
    tc = mixer.trackCount() - 1
    fx = {}
    for i in range(tc):
        for sl in range(10):
            if mixer.isTrackPluginValid(i, sl):
                try:
                    fx['%d.%d' % (i, sl)] = plugins.getPluginName(i, sl)
                except Exception:
                    fx['%d.%d' % (i, sl)] = '?'
    return {'ch': ch, 'tc': tc, 'fx': fx}


def walker():
    """Passe de fond complete sur l'etat, une unite de travail par yield."""
    while True:
        sig = struct_sig()
        if sig != ST['fp']:
            ST['fp'] = sig
            LINK.send({'t': 'struct', 'fp': sig})
        yield
        n = channels.channelCount(True)
        for g in range(n):
            scan_channel(g)
            yield
            scan_grid(g)
            yield
        tc = mixer.trackCount() - 1
        for i in range(tc):
            scan_mixer(i)
            yield
        if ST['passes'] % 4 == 0:
            for i in range(tc):
                scan_routes(i, tc)
                yield
        pm = min(patterns.patternMax(), 999)
        for b in range(1, pm + 1, 50):
            for k in range(b, min(b + 50, pm + 1)):
                for f, (get, _) in PAT.items():
                    see('p.%d.%s' % (k, f), get(k))
            yield
        ptc = playlist.trackCount()
        for b in range(1, ptc + 1, 50):
            for k in range(b, min(b + 50, ptc + 1)):
                for f, (get, _) in PLT.items():
                    see('l.%d.%s' % (k, f), get(k))
            yield
        if not transport.isPlaying():
            for g in range(n):
                for _ in plugin_units(g, None):
                    yield
            for i in range(tc):
                for s in range(10):
                    if mixer.isTrackPluginValid(i, s):
                        for _ in plugin_units(i, s):
                            yield
        ST['passes'] += 1
        ST['warm'] = False
        yield


# ------------------------------------------------------ application ops ----
def apply_op(k, v):
    a = k.split('.')
    h = a[0]
    if h == 'm':
        i = int(a[1])
        f = a[2]
        if f == 'r':
            d = int(a[3])
            set_route(i, d, v)
            S[k] = get_route(i, d)
        elif f in EQ:
            b = int(a[3])
            EQ[f][1](i, b, v)
            S[k] = EQ[f][0](i, b)
        else:
            MIX[f][1](i, v)
            S[k] = MIX[f][0](i)
    elif h == 'c':
        g = int(a[1])
        CH[a[2]][1](g, v)
        S[k] = CH[a[2]][0](g)
    elif h == 'g':
        pat = int(a[1])
        g = int(a[2])
        if pat == patterns.patternNumber():
            set_grid(g, v)
            S[k] = get_grid(g)
        else:
            DEFER.setdefault(pat, {})[g] = v
            S[k] = v
    elif h == 'x':
        g = int(a[1])
        p = int(a[2])
        if 'x.%d' % g in SKIP:
            return
        plugins.setParamValue(v, p, g, -1, 0, True)
        S[k] = r4(plugins.getParamValue(p, g, -1, True))
    elif h == 'y':
        i = int(a[1])
        s = int(a[2])
        p = int(a[3])
        if 'y.%d.%d' % (i, s) in SKIP:
            return
        plugins.setParamValue(v, p, i, s)
        S[k] = r4(plugins.getParamValue(p, i, s))
    elif h == 'p':
        n = int(a[1])
        PAT[a[2]][1](n, v)
        S[k] = PAT[a[2]][0](n)
    elif h == 'l':
        i = int(a[1])
        PLT[a[2]][1](i, v)
        S[k] = PLT[a[2]][0](i)
    elif h == 't':
        set_tempo(v)
        S[k] = get_tempo()
    elif h == 'ts':
        if ST['follow']:
            transport.setSongPos(int(v), 2)
    elif h == 'tp':
        if ST['follow'] and int(transport.isPlaying()) != int(v):
            if v:
                transport.start()
            else:
                transport.stop()
            ST['play'] = int(v)


def handle(msg):
    t = msg.get('t')
    if t == 'ops':
        if not ST['live']:
            return
        for k, v in msg.get('o', ()):
            try:
                apply_op(k, v)
            except Exception:
                pass
    elif t == 'cfg':
        live = bool(msg.get('live'))
        if live and not ST['live']:
            S.clear()
            DEFER.clear()
            ST['play'] = None
            ST['pat'] = -1
            ST['walker'] = None     # la reference repart du debut, a cadence acceleree
            ST['warm'] = True
        ST['live'] = live
        ST['follow'] = bool(msg.get('follow'))
        SKIP.clear()
        SKIP.update(msg.get('skip') or ())
    elif t == 'save':
        transport.globalTransport(midi.FPT_Save, 1)
    elif t == 'notify':
        ui.setHintMsg(str(msg.get('msg', '')))
    elif t == 'fp?':
        ST['fp'] = struct_sig()
        LINK.send({'t': 'struct', 'fp': ST['fp'], 'reply': 1})


def presence(now):
    if now - ST['pres_t'] < 0.5:
        return
    ST['pres_t'] = now
    win = -1
    for w in range(5):
        if ui.getFocused(w):
            win = w
            break
    if win < 0 and ui.getFocusedPluginName():
        win = 6
    p = (title(), patterns.patternNumber(), win, int(transport.isPlaying()), int(general.getChangedFlag()))
    if p != ST['pres']:
        ST['pres'] = p
        LINK.send({'t': 'pres', 'title': p[0], 'pat': p[1], 'win': p[2], 'play': p[3], 'dirty': p[4]})


# ------------------------------------------------------------ callbacks ----
def tick():
    now = time.perf_counter()
    msgs = LINK.poll(now)
    if not LINK.up or ST['loading']:
        return
    for m in msgs:
        handle(m)
    presence(now)
    budget = BUDGET_WARM if ST['warm'] else (BUDGET_HOT if now < ST['boost'] else BUDGET)
    end = now + budget
    scan_global()
    # 1) indices donnes par FL (pistes / canaux modifies)
    hot = ST['hot']
    while hot and time.perf_counter() < end:
        kind, idx = hot.pop()
        try:
            if kind == 'm':
                if 0 <= idx < mixer.trackCount() - 1:
                    scan_mixer(idx)
            elif 0 <= idx < channels.channelCount(True):
                scan_channel(idx)
                scan_grid(idx)
        except Exception:
            pass
    # 2) plugin au premier plan : c'est celui que l'utilisateur manipule
    fo = focused_plugin()
    if fo != ST['focus']:
        ST['focus'] = fo
        ST['fgen'] = None
    if fo is not None:
        half = time.perf_counter() + budget * 0.5
        while time.perf_counter() < half:
            gen = ST.get('fgen')
            if gen is None:
                gen = ST['fgen'] = plugin_units(fo[0], fo[1])
            try:
                next(gen)
            except StopIteration:
                ST['fgen'] = None
                break
            except Exception:
                ST['fgen'] = None
                break
    # 3) passe de fond
    while time.perf_counter() < end:
        w = ST['walker']
        if w is None:
            w = ST['walker'] = walker()
        try:
            next(w)
        except Exception:
            ST['walker'] = None
            break
    if OUT:
        LINK.send({'t': 'ops', 'o': OUT[:]})
        del OUT[:]


def OnInit():
    ST['walker'] = None
    pass


def OnDeInit():
    LINK.close()


def OnIdle():
    try:
        tick()
    except Exception:
        log('tick: ' + traceback.format_exc())


def OnRefresh(flags):
    ST['boost'] = time.perf_counter() + 0.5


def OnDirtyMixerTrack(index):
    ST['boost'] = time.perf_counter() + 0.5
    if index >= 0 and len(ST['hot']) < 64:
        ST['hot'].append(('m', index))


def OnDirtyChannel(index, flag=0):
    ST['boost'] = time.perf_counter() + 0.5
    if index >= 0 and len(ST['hot']) < 64:
        ST['hot'].append(('c', index))


def OnSysEx(event):
    try:
        LINK.on_sysex(event.sysex)
    except Exception:
        log('sysex: ' + traceback.format_exc())
    event.handled = True


def OnProjectLoad(status):
    if status == 0:
        ST['loading'] = True
        ST['live'] = False
    else:
        ST['loading'] = False
        S.clear()
        DEFER.clear()
        PCOUNT.clear()
        ST['walker'] = None
        ST['fp'] = None
        ST['pres'] = None
        ST['play'] = None
        ST['pat'] = -1
        LINK.send({'t': 'loaded', 'ok': status == 100, 'title': title()})
