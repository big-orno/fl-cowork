"""Test de la fusion de projets (notes, playlist, decalage des chevauchements)."""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cowork import env, flp  # noqa: E402


def item(pos, length, track):
    b = bytearray(80)
    struct.pack_into('<IHHI', b, 0, pos, 0x5000, 0x5001, length)
    struct.pack_into('<H', b, 12, track)
    return bytes(b)


def note(pos, key):
    b = bytearray(24)
    struct.pack_into('<IHHIHH', b, 0, pos, 0, 0, 96, key, 0)
    return bytes(b)


def make(tpl, items, notes):
    evs, pat = [], None
    done = False
    for e, r in flp.events(tpl):
        if e == flp.NEW_PAT:
            pat = struct.unpack('<H', r[:2])[0]
        if e == flp.PLAYLIST:
            r = b''.join(items)
        if e == flp.NOTES and pat == 1 and not done:
            r = b''.join(notes)
            done = True
        evs.append((e, r))
    return flp._build(flp._head(tpl), evs)


def read(data):
    n, i, _, _ = flp._scan(list(flp.events(data)))
    return n.get(1, []), i


tpl = open(env.empty_template(), 'rb').read()
evs = [(e, r) for e, r in flp.events(tpl) if e not in (flp.NEW_PAT, flp.NOTES)]
k = next(i for i, (e, _) in enumerate(evs) if e == flp.PLAYLIST)
evs[k:k] = [(flp.NEW_PAT, bytes((1, 0))), (flp.NOTES, b'')]
tpl = flp._build(flp._head(tpl), evs)
base = make(tpl, [item(0, 384, 499)], [note(0, 60)])
mine = make(tpl, [item(0, 384, 499), item(100, 384, 499)], [note(0, 60), note(96, 64)])
theirs = make(tpl, [item(0, 384, 499), item(50, 200, 499)], [note(0, 60), note(192, 67)])
out, rep = flp.merge(base, mine, theirs)
notes, items = read(out)
assert rep['ok'] and rep['notes'] == 1 and rep['items'] == 1 and rep['moved'] == 1, rep
assert sorted(struct.unpack_from('<I', n)[0] for n in notes) == [0, 96, 192], notes
tracks = sorted((struct.unpack_from('<I', x)[0], flp._track(x)) for x in items)
assert tracks == [(0, 499), (50, 499), (100, 498)], tracks
assert read(flp.merge(base, theirs, theirs)[0])[1] == read(theirs)[1]
out2, rep2 = flp.merge(base, base + b'', theirs)
assert out2 == theirs
v = flp.set_version(theirs, '24.0.0.1')
assert flp.version_of(v) == '24.0.0.1' and read(v) == read(theirs)
print('FUSION OK')
