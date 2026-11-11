"""Lecture minimale du format .flp : extrait les chemins des samples references."""
import os
import struct

SAMPLE_PATH = 196  # evenement texte : chemin de fichier d'un canal sampler / audio clip


def events(data):
    if data[:4] != b'FLhd':
        raise ValueError('pas un fichier FLP')
    (hlen,) = struct.unpack('<I', data[4:8])
    pos = 8 + hlen
    if data[pos:pos + 4] != b'FLdt':
        raise ValueError('FLP corrompu')
    pos += 8
    n = len(data)
    while pos < n:
        eid = data[pos]
        pos += 1
        if eid < 64:
            size = 1
        elif eid < 128:
            size = 2
        elif eid < 192:
            size = 4
        else:
            size = 0
            shift = 0
            while True:
                b = data[pos]
                pos += 1
                size |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        yield eid, data[pos:pos + size]
        pos += size


def _text(raw):
    if len(raw) >= 2 and len(raw) % 2 == 0 and b'\x00' in raw[1::2]:
        return raw.decode('utf-16-le', 'ignore').rstrip('\x00')
    return raw.decode('utf-8', 'ignore').rstrip('\x00')


def resolve(raw, flp_path, fl_user_data=''):
    """Chemin absolu d'un sample tel qu'ecrit dans le projet ('' si d'usine)."""
    if not raw or '%FLStudioFactoryData%' in raw:
        return ''
    p = raw.replace('%FLStudioUserData%', fl_user_data.rstrip('\\/'))
    p = os.path.expandvars(p)
    if not os.path.isabs(p):
        p = os.path.join(os.path.dirname(flp_path), p)
    return os.path.normpath(p)


def sample_refs(flp_path, fl_user_data='', fl_install=''):
    """[(texte brut du projet, chemin absolu)] des samples utilisateur references.

    Les samples d'usine sont ignores : tout le monde les a. Le chemin absolu
    peut ne pas exister (sample deplace ou supprime).
    """
    with open(flp_path, 'rb') as f:
        data = f.read()
    out = []
    seen = set()
    try:
        for eid, raw in events(data):
            if eid != SAMPLE_PATH:
                continue
            text = _text(raw)
            p = resolve(text, flp_path, fl_user_data)
            if not p or (fl_install and p.lower().startswith(fl_install.lower())):
                continue
            if text not in seen:
                seen.add(text)
                out.append((text, p))
    except (IndexError, ValueError):
        pass
    return out


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def rewrite_samples(src, dst, mapping):
    """Copie src vers dst en remplacant les chemins de samples.

    mapping : {texte brut du projet: nouveau chemin absolu}. Renvoie le nombre
    de chemins remplaces. Le reste du fichier est recopie a l'octet pres.
    """
    with open(src, 'rb') as f:
        data = f.read()
    if data[:4] != b'FLhd':
        raise ValueError('pas un fichier FLP')
    (hlen,) = struct.unpack('<I', data[4:8])
    dpos = 8 + hlen
    if data[dpos:dpos + 4] != b'FLdt':
        raise ValueError('FLP corrompu')
    pos = dpos + 8
    out = bytearray(data[:pos])
    n = len(data)
    count = 0
    while pos < n:
        start = pos
        eid = data[pos]
        pos += 1
        if eid < 64:
            size = 1
        elif eid < 128:
            size = 2
        elif eid < 192:
            size = 4
        else:
            size = 0
            shift = 0
            while True:
                b = data[pos]
                pos += 1
                size |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        raw = data[pos:pos + size]
        pos += size
        new = mapping.get(_text(raw)) if eid == SAMPLE_PATH else None
        if new:
            wide = len(raw) >= 2 and len(raw) % 2 == 0 and b'\x00' in raw[1::2]
            enc = (new + '\x00').encode('utf-16-le' if wide else 'utf-8')
            out += bytes((eid,)) + _varint(len(enc)) + enc
            count += 1
        else:
            out += data[start:pos]
    out[dpos + 4:dpos + 8] = struct.pack('<I', len(out) - dpos - 8)
    with open(dst, 'wb') as f:
        f.write(out)
    return count


# ---------------------------------------------------------------- fusion de versions
NEW_PAT, NEW_CHAN, NOTES, PLAYLIST, FL_VERSION = 65, 64, 224, 233, 199
NOTE_SIZE, ITEM_SIZE = 24, 80


def _head(data):
    (hlen,) = struct.unpack('<I', data[4:8])
    return data[:8 + hlen]


def _encode(eid, raw):
    if eid < 192:
        return bytes((eid,)) + raw
    return bytes((eid,)) + _varint(len(raw)) + raw


def _build(head, evs):
    body = b''.join(_encode(e, r) for e, r in evs)
    return head + b'FLdt' + struct.pack('<I', len(body)) + body


def _chunks(raw, size):
    return [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]


def _scan(evs):
    """({motif: [notes]}, [elements de playlist], motifs, nombre de canaux)."""
    notes, items, pats, chans, cur = {}, [], [], 0, None
    for e, r in evs:
        if e == NEW_PAT:
            cur = struct.unpack('<H', r[:2])[0]
            if cur not in pats:
                pats.append(cur)
        elif e == NEW_CHAN:
            chans += 1
        elif e == NOTES and cur is not None:
            notes.setdefault(cur, []).extend(_chunks(r, NOTE_SIZE))
        elif e == PLAYLIST:
            items.extend(_chunks(r, ITEM_SIZE))
    return notes, items, pats, chans


def _merge_lists(base, mine, theirs):
    """Fusion a trois voies d'une liste d'enregistrements : ce que 'mine' a ajoute
    ou retire par rapport a 'base' est reporte sur 'theirs'. Renvoie (liste, ajouts)."""
    from collections import Counter
    cb, cm = Counter(base), Counter(mine)
    added = cm - cb
    removed = cb - cm
    out = []
    drop = Counter(removed)
    for x in theirs:
        if drop[x] > 0:
            drop[x] -= 1
        else:
            out.append(x)
    new = []
    for x in mine:
        if added[x] > 0:
            added[x] -= 1
            new.append(x)
    return out, new


def _track(item):
    return struct.unpack_from('<H', item, 12)[0]


def _span(item):
    pos, length = struct.unpack_from('<I', item, 0)[0], struct.unpack_from('<I', item, 8)[0]
    return pos, pos + max(length, 1)


def _spread(kept, new):
    """Place les elements ajoutes sans chevaucher ceux d'une meme piste : decales
    vers le bas (pistes suivantes), puis vers le haut. Renvoie (liste, nb de decales)."""
    busy = {}
    for it in kept:
        busy.setdefault(_track(it), []).append(_span(it))
    moved = 0
    placed = []

    def free(t, s):
        return all(s[1] <= a or s[0] >= b for a, b in busy.get(t, ()))
    for it in new:
        t, s = _track(it), _span(it)
        if not free(t, s):
            cand = [t - d for d in range(1, t + 1)] + [t + d for d in range(1, 500 - t)]  # rvidx : bas = valeurs decroissantes
            for c in cand:
                if 0 <= c < 500 and free(c, s):
                    it = it[:12] + struct.pack('<H', c) + it[14:]
                    t = c
                    moved += 1
                    break
        busy.setdefault(t, []).append(s)
        placed.append(it)
    return placed, moved


def version_of(data):
    for e, r in events(data):
        if e == FL_VERSION:
            return r.rstrip(b'\x00').decode('ascii', 'ignore')
    return ''


def _vtuple(v):
    try:
        return tuple(int(x) for x in v.split('.'))
    except ValueError:
        return ()


def set_version(data, version):
    """Ecrit la version de FL du projet (evite l'avertissement « projet d'une version plus recente »)."""
    evs = [(e, (version.encode('ascii') + b'\x00') if e == FL_VERSION else r) for e, r in events(data)]
    return _build(_head(data), evs)


def _merge_blob(eid, b, m, t, rep):
    """Fusion du contenu d'un evenement de notes (224) ou de playlist (233)."""
    size = NOTE_SIZE if eid == NOTES else ITEM_SIZE
    out, new = _merge_lists(_chunks(b, size), _chunks(m, size), _chunks(t, size))
    if eid == NOTES:
        rep['notes'] += len(new)
        return b''.join(out + new)
    new = [x for x in new if x not in out]
    placed, moved = _spread(out, new)
    rep['items'] += len(new)
    rep['moved'] += moved
    return b''.join(out + placed)


def _resolve(bs, ms, ts, rep):
    """Zone modifiee des deux cotes : renvoie la liste d'evenements retenue."""
    if ms == ts:
        return ts
    if not bs and not any(e in (NEW_CHAN, NEW_PAT) for e, _ in ms + ts):
        return ts + ms                      # ajouts independants au meme endroit : on garde tout
    if len(bs) == len(ms) == len(ts) and all(b[0] == m[0] == t[0] for b, m, t in zip(bs, ms, ts)):
        out = []
        for b, m, t in zip(bs, ms, ts):
            if m == t:
                out.append(t)
            elif m == b:
                out.append(t)
            elif t == b:
                out.append(m)
            elif b[0] in (NOTES, PLAYLIST):
                out.append((b[0], _merge_blob(b[0], b[1], m[1], t[1], rep)))
            else:
                out.append(m)
                rep['conflicts'] += 1
        return out
    rep['conflicts'] += 1
    return ms                                # la version de celui qui enregistre l'emporte


def merge(base, mine, theirs):
    """Fusion a trois voies de deux versions d'un projet ayant une origine commune.

    Les modifications locales (mine, par rapport a base) sont reportees sur la version
    recue (theirs) : ce qui n'a ete touche que d'un cote est repris tel quel, notes et
    playlist touchees des deux cotes sont combinees (un clip qui en chevauche un autre
    est decale sur une piste libre), le reste en conflit prend la valeur locale.
    Renvoie (octets, rapport) ; rapport : ok, changed, notes, items, moved, conflicts, why.
    """
    import difflib
    rep = {'ok': False, 'changed': False, 'notes': 0, 'items': 0, 'moved': 0, 'conflicts': 0, 'why': ''}
    try:
        eb, em, et = list(events(base)), list(events(mine)), list(events(theirs))
    except (ValueError, IndexError):
        rep['why'] = 'fichier illisible'
        return theirs, rep
    if em == eb:
        rep['ok'] = True
        return theirs, rep
    hunks = []
    for side, ev in (('m', em), ('t', et)):
        sm = difflib.SequenceMatcher(None, eb, ev, autojunk=False)
        hunks += [(i1, i2, side, j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']
    hunks.sort(key=lambda h: (h[0], h[1], h[2]))
    groups = []
    for h in hunks:
        g = groups[-1] if groups else None
        if g and (h[0] < g['hi'] or (h[0] == g['hi'] and (g['lo'] == g['hi'] or h[0] == h[1]) and g['lo'] == g['hi'])):
            g['hunks'].append(h)
            g['hi'] = max(g['hi'], h[1])
        else:
            groups.append({'lo': h[0], 'hi': h[1], 'hunks': [h]})
    src = {'m': em, 't': et}

    def seg(g, side):
        out, pos = [], g['lo']
        for i1, i2, sd, j1, j2 in g['hunks']:
            if sd != side:
                continue
            out += eb[pos:i1] + src[side][j1:j2]
            pos = i2
        return out + eb[pos:g['hi']]
    res, pos = [], 0
    for g in groups:
        res += eb[pos:g['lo']]
        pos = g['hi']
        sides = {h[2] for h in g['hunks']}
        if len(sides) == 1:
            res += seg(g, sides.pop())
        else:
            res += _resolve(eb[g['lo']:g['hi']], seg(g, 'm'), seg(g, 't'), rep)
    res += eb[pos:]
    # les hunks d'un meme cote sont traites dans l'ordre de la base : on a bien reconstruit « base + m + t »
    rep['ok'] = True
    if res == et:
        return theirs, rep
    rep['changed'] = True
    return _build(_head(theirs), res), rep
