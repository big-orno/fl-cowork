"""Faux FL Studio : implemente la partie de l'API de script utilisee par FL Cowork.

Plusieurs "mondes" (un par participant simule) ; CUR designe celui sur lequel
agissent les appels en cours.
"""
import sys
import types

CUR = None


class World:
    def __init__(self, nch=4, ntracks=127):
        self.title = 'FL Studio'
        self.tempo = 140.0
        self.playing = False
        self.songpos = 0
        self.pat = 1
        self.dirty = 0
        self.saves = 0
        self.focus_plugin = None   # index global de canal dont le plugin est au premier plan
        self.tracks = [{'v': 0.8, 'p': 0.0, 'ss': 0.0, 'mu': 0, 'en': 1, 'n': 'Insert %d' % i, 'c': 0x565656,
                        'eq': [[0.0, 0.3, 0.5] for _ in range(3)], 'routes': {}, 'slots': {}}
                       for i in range(ntracks)]
        self.chans = [{'v': 0.78, 'p': 0.0, 'pi': 0.0, 'mu': 0, 'fx': 0, 'n': 'Canal %d' % i, 'c': 0x5f6b72,
                       'plugin': 'Sytrus' if i == 0 else None, 'params': [0.5] * 40}
                      for i in range(nch)]
        self.grid = {}
        self.pats = {}
        self.pl = {}


def _mod(name, **fns):
    m = types.ModuleType(name)
    m.__dict__.update(fns)
    sys.modules[name] = m
    return m


def W():
    return CUR


def _ch(g):
    return CUR.chans[g]


def _setch(f):
    def fn(g, v, *a):
        CUR.chans[g][f] = v
        CUR.dirty = 1
    return fn


def _settr(f, conv=lambda v: v):
    def fn(i, v, *a):
        CUR.tracks[i][f] = conv(v)
        CUR.dirty = 1
    return fn


def _route_set(i, d, on, *a):
    if on:
        CUR.tracks[i]['routes'].setdefault(d, 1.0)
    else:
        CUR.tracks[i]['routes'].pop(d, None)


def _params(index, slot):
    if slot == -1 or slot is None:
        return CUR.chans[index]['params']
    return CUR.tracks[index]['slots'][slot]


def _set_param(v, p, index, slot=-1, *a):
    _params(index, slot)[p] = v
    CUR.dirty = 1


def _global_transport(cmd, value, *a):
    if cmd == 92:
        CUR.saves += 1
        CUR.dirty = 0
    return 0


def _rec_event(eid, value, flags):
    if eid == 5000:
        CUR.tempo = value / 1000.0
    return 0


_mod('device', midiOutSysex=lambda b: None)
_mod('midi', PIM_None=0, REC_Tempo=5000, REC_Control=1, REC_UpdateControl=2, FPT_Save=92)
_mod('mixer',
     trackCount=lambda: len(CUR.tracks),
     getTrackVolume=lambda i, m=0: CUR.tracks[i]['v'], setTrackVolume=_settr('v'),
     getTrackPan=lambda i: CUR.tracks[i]['p'], setTrackPan=_settr('p'),
     getTrackStereoSep=lambda i: CUR.tracks[i]['ss'], setTrackStereoSep=_settr('ss'),
     isTrackMuted=lambda i: bool(CUR.tracks[i]['mu']), muteTrack=_settr('mu', int),
     isTrackSlotsEnabled=lambda i: bool(CUR.tracks[i]['en']), enableTrackSlots=_settr('en', int),
     getTrackName=lambda i: CUR.tracks[i]['n'], setTrackName=_settr('n'),
     getTrackColor=lambda i: CUR.tracks[i]['c'], setTrackColor=_settr('c'),
     getEqGain=lambda i, b, m=0: CUR.tracks[i]['eq'][b][0],
     getEqFrequency=lambda i, b, m=0: CUR.tracks[i]['eq'][b][1],
     getEqBandwidth=lambda i, b: CUR.tracks[i]['eq'][b][2],
     setEqGain=lambda i, b, v: CUR.tracks[i]['eq'][b].__setitem__(0, v),
     setEqFrequency=lambda i, b, v: CUR.tracks[i]['eq'][b].__setitem__(1, v),
     setEqBandwidth=lambda i, b, v: CUR.tracks[i]['eq'][b].__setitem__(2, v),
     getRouteSendActive=lambda i, d: d in CUR.tracks[i]['routes'],
     getRouteToLevel=lambda i, d: CUR.tracks[i]['routes'][d],
     setRouteTo=_route_set,
     setRouteToLevel=lambda i, d, v: CUR.tracks[i]['routes'].__setitem__(d, v),
     afterRoutingChanged=lambda: None,
     isTrackPluginValid=lambda i, s: s in CUR.tracks[i]['slots'],
     getCurrentTempo=lambda asInt=False: CUR.tempo)
_mod('channels',
     channelCount=lambda g=False: len(CUR.chans),
     getChannelVolume=lambda g, m=False, u=False: _ch(g)['v'], setChannelVolume=_setch('v'),
     getChannelPan=lambda g, u=False: _ch(g)['p'], setChannelPan=_setch('p'),
     getChannelPitch=lambda g, m=0, u=False: _ch(g)['pi'], setChannelPitch=_setch('pi'),
     isChannelMuted=lambda g, u=False: bool(_ch(g)['mu']), muteChannel=_setch('mu'),
     getTargetFxTrack=lambda g, u=False: _ch(g)['fx'], setTargetFxTrack=_setch('fx'),
     getChannelName=lambda g, u=False: _ch(g)['n'], setChannelName=_setch('n'),
     getChannelColor=lambda g, u=False: _ch(g)['c'], setChannelColor=_setch('c'),
     getGridBit=lambda g, s, u=False: bool(CUR.grid.get((CUR.pat, g), 0) >> s & 1),
     setGridBit=lambda g, s, v, u=False: CUR.grid.__setitem__(
         (CUR.pat, g), (CUR.grid.get((CUR.pat, g), 0) & ~(1 << s)) | (int(bool(v)) << s)))
_mod('patterns',
     patternNumber=lambda: CUR.pat, patternMax=lambda: 60,
     getPatternName=lambda n: CUR.pats.get(n, {}).get('n', 'Pattern %d' % n),
     getPatternColor=lambda n: CUR.pats.get(n, {}).get('c', 0),
     setPatternName=lambda n, v: CUR.pats.setdefault(n, {}).__setitem__('n', v),
     setPatternColor=lambda n, v: CUR.pats.setdefault(n, {}).__setitem__('c', v))
_mod('playlist',
     trackCount=lambda: 20,
     getTrackName=lambda i: CUR.pl.get(i, {}).get('n', 'Track %d' % i),
     getTrackColor=lambda i: CUR.pl.get(i, {}).get('c', 0),
     isTrackMuted=lambda i: bool(CUR.pl.get(i, {}).get('mu', 0)),
     setTrackName=lambda i, v: CUR.pl.setdefault(i, {}).__setitem__('n', v),
     setTrackColor=lambda i, v: CUR.pl.setdefault(i, {}).__setitem__('c', v),
     muteTrack=lambda i, v=-1: CUR.pl.setdefault(i, {}).__setitem__('mu', int(v)))
_mod('plugins',
     isValid=lambda i, s=-1, u=False: (CUR.chans[i]['plugin'] is not None) if s == -1 else s in CUR.tracks[i]['slots'],
     getParamCount=lambda i, s=-1, u=False: len(_params(i, s)),
     getParamValue=lambda p, i, s=-1, u=False: _params(i, s)[p],
     setParamValue=_set_param,
     getPluginName=lambda i, s=-1, user=False, u=False: (CUR.chans[i]['plugin'] if s == -1 else 'FX'))
_mod('general', processRECEvent=_rec_event, getChangedFlag=lambda: CUR.dirty)
_mod('transport',
     isPlaying=lambda: CUR.playing, getSongPos=lambda m=-1: CUR.songpos,
     setSongPos=lambda v, m=-1: setattr(CUR, 'songpos', v),
     start=lambda: setattr(CUR, 'playing', True), stop=lambda: setattr(CUR, 'playing', False),
     globalTransport=_global_transport)
_mod('ui',
     getProgTitle=lambda: CUR.title, getFocused=lambda w: w == 0,
     getFocusedPluginName=lambda: 'Sytrus' if CUR.focus_plugin is not None else '',
     getFocusedFormID=lambda: CUR.focus_plugin if CUR.focus_plugin is not None else 0,
     setHintMsg=lambda m: None)
