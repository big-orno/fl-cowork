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
    notes, items, pat = [], [], None
    for e, r in flp.events(data):
        if e == flp.NEW_PAT:
            pat = struct.unpack('<H', r[:2])[0]
        elif e == flp.NOTES and pat == 1:
            notes += flp._chunks(r, 24)
        elif e == flp.PLAYLIST:
            items += flp._chunks(r, 80)
    return notes, items


def add_channel(data, name):
    """Ajoute un canal complet (evenement 64 + son nom) apres le dernier canal."""
    evs = list(flp.events(data))
    last = max(i for i, (e, _) in enumerate(evs) if e == flp.NEW_CHAN)
    k = last + 1
    while k < len(evs) and evs[k][0] not in (flp.NEW_CHAN, flp.NEW_PAT, flp.PLAYLIST):
        k += 1
    n = sum(1 for e, _ in evs if e == flp.NEW_CHAN)
    evs[k:k] = [(flp.NEW_CHAN, struct.pack('<H', n)), (203, name.encode('utf-16-le') + bytes((0, 0)))]
    return flp._build(flp._head(data), evs)


def tempo(data, v):
    return flp._build(flp._head(data), [(e, struct.pack('<I', v) if e == 156 else r) for e, r in flp.events(data)])


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
assert rep['ok'] and rep['changed'] and rep['notes'] == 1 and rep['items'] == 1 and rep['moved'] == 1, rep
assert sorted(struct.unpack_from('<I', n)[0] for n in notes) == [0, 96, 192], notes
tracks = sorted((struct.unpack_from('<I', x)[0], flp._track(x)) for x in items)
assert tracks == [(0, 499), (50, 499), (100, 498)], tracks

# rien de local : on reprend la version recue telle quelle
o, r = flp.merge(base, base, theirs)
assert o == theirs and not r['changed']

# canal ajoute en local + notes ajoutees par l'autre : tout est conserve
mine2 = add_channel(base, 'Ma basse')
nch = lambda d: sum(1 for e, _ in flp.events(d) if e == flp.NEW_CHAN)  # noqa: E731
o, r = flp.merge(base, mine2, theirs)
assert r['ok'] and r['changed'] and r['conflicts'] == 0, r
assert nch(o) == nch(base) + 1 and len(read(o)[0]) == 2 and len(read(o)[1]) == 2, (r, nch(o))
assert any(e == 203 and 'Ma'.encode('utf-16-le') in x for e, x in flp.events(o))

# l'autre ajoute un canal, moi des notes
o, r = flp.merge(base, mine, add_channel(theirs, 'Sa lead'))
assert r['ok'] and nch(o) == nch(base) + 1 and len(read(o)[0]) == 3 and r['conflicts'] == 0, r

# le meme reglage change des deux cotes : la version locale gagne
b2 = tempo(base, 120000)
o, r = flp.merge(b2, tempo(b2, 130000), tempo(b2, 140000))
assert r['conflicts'] == 1 and any(e == 156 and struct.unpack('<I', x)[0] == 130000 for e, x in flp.events(o)), r
# reglages differents : les deux sont gardes
o, r = flp.merge(b2, mine, tempo(b2, 140000))
assert r['conflicts'] == 0 and any(e == 156 and struct.unpack('<I', x)[0] == 140000 for e, x in flp.events(o))
assert len(read(o)[0]) == 2

# --- playlist : pas de doublons -------------------------------------------------
def clip(pos, length, track, pat=1, serial=1, flags=0):
    b = bytearray(item(pos, length, track))
    struct.pack_into('<HI', b, 6, 0x5000 + pat, 0)
    struct.pack_into('<I', b, 8, length)
    struct.pack_into('<I', b, 32, serial)
    b[55] = flags
    return bytes(b)


def pl(data):
    return sorted((struct.unpack_from('<I', x, 0)[0], flp._track(x), struct.unpack_from('<I', x, 32)[0])
                  for x in read(data)[1])


B = [clip(0, 384, 499, serial=1), clip(384, 384, 499, serial=2), clip(0, 384, 498, 2, serial=3)]
base = make(tpl, B, [note(0, 60)])
# l'autre machine a renumerote les series et change des octets sans importance : rien ne doit bouger
other = make(tpl, [clip(0, 384, 499, serial=11, flags=1), clip(384, 384, 499, serial=12),
                   clip(0, 384, 498, 2, serial=13, flags=1)], [note(0, 60)])
o, r = flp.merge(base, make(tpl, B + [clip(768, 384, 499, serial=4)], [note(0, 60)]), other)
got = [(p_, t_) for p_, t_, _ in pl(o)]
assert got == [(0, 498), (0, 499), (384, 499), (768, 499)], got
assert r['moved'] == 0, r
# les deux ajoutent le meme clip au meme endroit : un seul
same_a = make(tpl, B + [clip(768, 384, 499, serial=4)], [note(0, 60)])
same_b = make(tpl, B + [clip(768, 384, 499, serial=9)], [note(0, 60)])
o, r = flp.merge(base, same_a, same_b)
assert [(p_, t_) for p_, t_, _ in pl(o)].count((768, 499)) == 1 and r['moved'] == 0, pl(o)
# un clip ajoute au meme endroit que celui de l'autre, d'un motif different : decale, pas fusionne
diff = make(tpl, B + [clip(768, 384, 499, 3, serial=4)], [note(0, 60)])
o, r = flp.merge(base, diff, same_b)
assert sorted((p_, t_) for p_, t_, _ in pl(o)).count((768, 499)) == 1 and (768, 498) in [(p_, t_) for p_, t_, _ in pl(o)], pl(o)
# memes clips deplaces des deux cotes : pas de copie en double
mv_a = make(tpl, [clip(0, 384, 499, serial=1), clip(1000, 384, 499, serial=2), B[2]], [note(0, 60)])
mv_b = make(tpl, [clip(0, 384, 499, serial=1), clip(2000, 384, 499, serial=2), B[2]], [note(0, 60)])
o, r = flp.merge(base, mv_a, mv_b)
assert len(pl(o)) == 3 and (1000, 499) in [(p_, t_) for p_, t_, _ in pl(o)], pl(o)
# suppression locale d'un clip que l'autre n'a pas touche
o, r = flp.merge(base, make(tpl, B[:2], [note(0, 60)]), other)
assert len(pl(o)) == 2, pl(o)
# numeros de serie toujours uniques
o, r = flp.merge(base, make(tpl, B + [clip(768, 384, 499, serial=12)], [note(0, 60)]), other)
ids = [x[2] for x in pl(o)]
assert len(ids) == len(set(ids)), ids

v = flp.set_version(theirs, '24.0.0.1')
assert flp.version_of(v) == '24.0.0.1' and read(v) == read(theirs)
print('FUSION OK')
