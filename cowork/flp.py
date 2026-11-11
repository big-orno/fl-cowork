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


def merge(base, mine, theirs):
    """Fusionne les modifications locales (mine, par rapport a base) dans la version recue (theirs).

    Notes du piano roll et elements de la playlist sont combines ; un element de
    playlist qui en chevauche un autre est decale sur une piste libre. Si la
    structure (canaux, motifs) a change en local, rien n'est fusionne.
    Renvoie (octets, rapport) ; rapport = {'ok', 'notes', 'items', 'moved', 'why'}.
    """
    rep = {'ok': False, 'notes': 0, 'items': 0, 'moved': 0, 'why': ''}
    try:
        eb, em, et = list(events(base)), list(events(mine)), list(events(theirs))
    except (ValueError, IndexError):
        rep['why'] = 'fichier illisible'
        return theirs, rep
    nb, ib, pb, cb = _scan(eb)
    nm, im, pm, cm = _scan(em)
    nt, it, pt, ct = _scan(et)
    if pm != pb or cm != cb:
        rep['why'] = 'structure modifiée en local (canaux ou motifs ajoutés/retirés)'
        return theirs, rep
    if pt != pb or ct != cb:
        rep['why'] = "structure modifiée dans la nouvelle version"
        return theirs, rep
    merged_notes = {}
    for p in pm:
        out, new = _merge_lists(nb.get(p, []), nm.get(p, []), nt.get(p, []))
        if new or len(out) != len(nt.get(p, [])):
            merged_notes[p] = out + new
            rep['notes'] += len(new)
    out_items, new_items = _merge_lists(ib, im, it)
    new_items = [x for x in new_items if x not in out_items]   # deja present (meme element des deux cotes)
    placed, moved = _spread(out_items, new_items)
    rep['items'], rep['moved'] = len(new_items), moved
    final_items = out_items + placed
    if not merged_notes and not new_items and len(out_items) == len(it):
        rep['ok'] = True
        return theirs, rep
    res, cur, wrote, pl_done = [], None, set(), False
    for e, r in et:
        if e == NEW_PAT:
            cur = struct.unpack('<H', r[:2])[0]
            res.append((e, r))
            if cur in merged_notes and cur not in wrote and cur not in nt:
                wrote.add(cur)
                res.append((NOTES, b''.join(merged_notes[cur])))
            continue
        if e == NOTES and cur in merged_notes:
            if cur not in wrote:
                wrote.add(cur)
                res.append((e, b''.join(merged_notes[cur])))
            continue
        if e == PLAYLIST:
            if not pl_done:
                pl_done = True
                res.append((e, b''.join(final_items)))
            continue
        res.append((e, r))
    rep['ok'] = True
    return _build(_head(theirs), res), rep
