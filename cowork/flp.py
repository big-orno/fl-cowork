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


def _note_key(n):
    return struct.unpack_from('<I', n, 0)[0], struct.unpack_from('<H', n, 6)[0], struct.unpack_from('<H', n, 12)[0]


def _item_key(it):
    """Identite d'un clip de playlist : position, piste, motif/echantillon. Les autres octets
    (numero de serie, selection...) changent d'une sauvegarde a l'autre et ne comptent pas."""
    return struct.unpack_from('<IHH', it, 0) + (_track(it),)


def _item_kind(it):
    return struct.unpack_from('<HHI', it, 4)


def _item_sig(it):
    """Contenu d'un clip sans les octets qui changent a chaque sauvegarde (numero de serie, selection)."""
    return it[:32] + it[36:54] + bytes(3) + it[57:]


def _note_sig(n):
    return n[:4] + bytes(2) + n[6:]


def _keyed(recs, key):
    out, seen = {}, {}
    for r in recs:
        k = key(r)
        n = seen.get(k, 0)
        seen[k] = n + 1
        out[(k, n)] = r
    return out


def _pairs(deleted, added, B, M, kind):
    """Deplacements : un element supprime et un element ajoute de meme nature (meme motif,
    meme longueur) forment un seul deplacement, quand l'appariement est sans ambiguite."""
    pairs = {}
    free = set(added)
    for d in sorted(deleted):
        c = [a for a in free if kind(M[a]) == kind(B[d])]
        if len(c) == 1:
            pairs[d] = c[0]
            free.discard(c[0])
    return pairs


def _merge_keyed(base, mine, theirs, key, sig, kind=None):
    """Fusion a trois voies d'une liste d'enregistrements, par identite (key) et non par contenu.

    Deux enregistrements de meme identite ne sont jamais dupliques. Renvoie
    (liste fusionnee, liste des enregistrements ajoutes par 'mine')."""
    B, M, T = _keyed(base, key), _keyed(mine, key), _keyed(theirs, key)
    res = dict(T)
    dm, am = set(B) - set(M), set(M) - set(B)
    dt, at = set(B) - set(T), set(T) - set(B)
    mv_m = _pairs(dm, am, B, M, kind) if kind else {}
    mv_t = _pairs(dt, at, B, T, kind) if kind else {}
    for k in dm:
        if k in mv_m and k in mv_t and mv_m[k] != mv_t[k]:
            res.pop(mv_t[k], None)             # deplace des deux cotes : la destination locale l'emporte
        if k in res and sig(T[k]) == sig(B[k]):
            del res[k]                         # supprime ici, intact la-bas (sinon modifie la-bas : on garde)
    for k in set(M) & set(B):
        if k in res and sig(M[k]) != sig(B[k]) and sig(M[k]) != sig(T[k]):
            res[k] = M[k]                      # modifie ici (par rapport a la base) : la modification suit
    new = []
    for k in M:
        if k in am and k not in res:
            res[k] = M[k]
            new.append(M[k])
    order = [k for k in T if k in res] + [k for k in M if k in res and k not in T]
    return [res[k] for k in order], new


def _renumber(items):
    """Numeros de serie des clips (octets 32-35) uniques, pour que FL ne les confonde pas."""
    used, out, nxt = set(), [], 0
    for it in items:
        nxt = max(nxt, struct.unpack_from('<I', it, 32)[0])
    for it in items:
        sid = struct.unpack_from('<I', it, 32)[0]
        if sid in used:
            nxt += 1
            sid = nxt
            it = it[:32] + struct.pack('<I', sid) + it[36:]
        used.add(sid)
        out.append(it)
    return out


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
    if eid == NOTES:
        out, new = _merge_keyed(_chunks(b, NOTE_SIZE), _chunks(m, NOTE_SIZE), _chunks(t, NOTE_SIZE), _note_key, _note_sig)
        rep['notes'] += len(new)
        return b''.join(out)
    out, new = _merge_keyed(_chunks(b, ITEM_SIZE), _chunks(m, ITEM_SIZE), _chunks(t, ITEM_SIZE),
                            _item_key, _item_sig, _item_kind)
    ids = {id(x) for x in new}
    kept = [x for x in out if id(x) not in ids]
    placed, moved = _spread(kept, new)
    rep['items'] += len(new)
    rep['moved'] += moved
    return b''.join(_renumber(kept + placed))


def _ids(evs):
    """Numeros de canaux et de motifs crees par une suite d'evenements."""
    out = set()
    for e, r in evs:
        if e == NEW_CHAN:
            out.add(('c', struct.unpack('<H', r[:2])[0]))
        elif e == NEW_PAT:
            out.add(('p', struct.unpack('<H', r[:2])[0]))
    return out


VOLATILE = (237, 199, 159)       # horodatage, version, compteur : changent a chaque sauvegarde
# Reglages propres a chaque utilisateur et a son FL Studio, jamais partages : volume et pitch
# generaux de FL, motif et filtre selectionnes, hauteur de fenetre, nom d'enregistrement, dossier
# de donnees, frequence d'echantillonnage, mode de lecture. Chacun garde les siens.
PERSONAL = (12, 80, 67, 146, 133, 217, 200, 202, 153, 9)
QUIET = VOLATILE + PERSONAL


def _remap(evs, chmap, patmap):
    """Renumerote canaux et motifs (evenements, notes, clips de playlist)."""
    out, cur = [], None
    for e, r in evs:
        if e == NEW_CHAN:
            old = struct.unpack('<H', r[:2])[0]
            cur = old if old in chmap else None
            if cur is not None:
                r = struct.pack('<H', chmap[old])
        elif e in (NEW_PAT, 99):
            cur = None
            if e == NEW_PAT:
                old = struct.unpack('<H', r[:2])[0]
                if old in patmap:
                    r = struct.pack('<H', patmap[old])
        elif cur is not None and e in (104, 132, 215):
            b = bytearray(r)
            for off in ((0,) if e == 104 else (0, 2) if e == 132 else (8,)):
                if struct.unpack_from('<H', b, off)[0] == cur:
                    struct.pack_into('<H', b, off, chmap[cur])
            r = bytes(b)
        elif e == NOTES and chmap:
            b = bytearray(r)
            for i in range(0, len(b) - NOTE_SIZE + 1, NOTE_SIZE):
                rack = struct.unpack_from('<H', b, i + 6)[0]
                if rack in chmap:
                    struct.pack_into('<H', b, i + 6, chmap[rack])
            r = bytes(b)
        elif e == PLAYLIST:
            b = bytearray(r)
            for i in range(0, len(b) - ITEM_SIZE + 1, ITEM_SIZE):
                idx = struct.unpack_from('<H', b, i + 6)[0]
                if idx >= 0x5000 and idx - 0x5000 in patmap:
                    struct.pack_into('<H', b, i + 6, 0x5000 + patmap[idx - 0x5000])
                elif idx < 0x5000 and idx in chmap:
                    struct.pack_into('<H', b, i + 6, chmap[idx])
            r = bytes(b)
        out.append((e, r))
    return out


def _structure(evs):
    chans, pats = [], []
    for e, r in evs:
        if e == NEW_CHAN:
            chans.append(struct.unpack('<H', r[:2])[0])
        elif e == NEW_PAT:
            v = struct.unpack('<H', r[:2])[0]
            if v not in pats:
                pats.append(v)
    return chans, pats


def _deconflict(eb, em, et):
    """Canaux ou motifs crees des deux cotes avec le meme numero : ceux du cote local sont
    renumerotes a la suite, pour que rien ne soit ecrase ni confondu."""
    cb, pb = _structure(eb)
    cm, pm = _structure(em)
    ct, pt = _structure(et)
    new_m_c = [c for c in cm if c not in cb]
    new_t_c = [c for c in ct if c not in cb]
    new_m_p = [p for p in pm if p not in pb]
    new_t_p = [p for p in pt if p not in pb]
    chmap, patmap = {}, {}
    if set(new_m_c) & set(new_t_c):
        nxt = max(cb + cm + ct + [-1]) + 1
        for c in new_m_c:
            if c in new_t_c:
                chmap[c] = nxt
                nxt += 1
    if set(new_m_p) & set(new_t_p):
        nxt = max(pb + pm + pt + [0]) + 1
        for p in new_m_p:
            if p in new_t_p:
                patmap[p] = nxt
                nxt += 1
    return (_remap(em, chmap, patmap) if chmap or patmap else em), bool(chmap or patmap)


def _semantic(evs):
    """Contenu qui compte : sans les champs volatils, avec clips et notes compares par identite."""
    out = []
    for e, r in evs:
        if e in QUIET:
            continue
        if e == PLAYLIST:
            r = b''.join(sorted(_item_sig(x) for x in _chunks(r, ITEM_SIZE)))
        elif e == NOTES:
            r = b''.join(sorted(_note_sig(x) for x in _chunks(r, NOTE_SIZE)))
        out.append((e, r))
    return out


def _lis(pairs):
    """Plus longue sous-suite croissante en j d'une liste de (i, j) triee par i."""
    import bisect
    tails, idx, prev = [], [], [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        pos = bisect.bisect_left(tails, j)
        if pos == len(tails):
            tails.append(j)
            idx.append(k)
        else:
            tails[pos] = j
            idx[pos] = k
        prev[k] = idx[pos - 1] if pos else -1
    out, k = [], idx[-1] if idx else -1
    while k >= 0:
        out.append(pairs[k])
        k = prev[k]
    return out[::-1]


def _diff(a, b, wa=None, wb=None):
    """Zones differentes entre deux suites d'entiers : [(i1, i2, j1, j2)].

    Methode « patience » : on s'appuie sur les elements presents une seule fois des deux
    cotes, ce qui evite le comportement quadratique de difflib sur les fichiers FL (milliers
    d'evenements quasi identiques)."""
    from collections import Counter
    import difflib
    out = []
    stack = [(0, len(a), 0, len(b))]
    while stack:
        i1, i2, j1, j2 = stack.pop()
        while i1 < i2 and j1 < j2 and a[i1] == b[j1]:
            i1 += 1
            j1 += 1
        while i1 < i2 and j1 < j2 and a[i2 - 1] == b[j2 - 1]:
            i2 -= 1
            j2 -= 1
        if i1 == i2 and j1 == j2:
            continue
        if i1 == i2 or j1 == j2:
            out.append((i1, i2, j1, j2))
            continue
        ca, cb = Counter(a[i1:i2]), Counter(b[j1:j2])
        where = {}
        for j in range(j1, j2):
            if cb[b[j]] == 1 and ca.get(b[j]) == 1:
                where[b[j]] = j
        pairs = [(i, where[a[i]]) for i in range(i1, i2) if a[i] in where]
        pairs = _lis(pairs)
        if not pairs and wa is not None and (i2 - i1) > 64 and (j2 - j1) > 64:
            # aucune ancre exacte : on s'appuie sur une cle faible (type d'evenement + 4 premiers octets,
            # p. ex. le numero de piste), les elements apparies sont alors compares un a un
            ca, cb = Counter(wa[i1:i2]), Counter(wb[j1:j2])
            where = {wb[j]: j for j in range(j1, j2) if cb[wb[j]] == 1 and ca.get(wb[j]) == 1}
            weak = _lis([(i, where[wa[i]]) for i in range(i1, i2) if wa[i] in where])
            if len(weak) > 16:
                pi, pj = i1, j1
                for i, j in weak:
                    stack.append((pi, i, pj, j))
                    if a[i] != b[j]:
                        out.append((i, i + 1, j, j + 1))
                    pi, pj = i + 1, j + 1
                stack.append((pi, i2, pj, j2))
                continue
        if not pairs:
            if (i2 - i1) * (j2 - j1) <= 4_000_000:
                sm = difflib.SequenceMatcher(None, a[i1:i2], b[j1:j2], autojunk=False)
                for tag, x1, x2, y1, y2 in sm.get_opcodes():
                    if tag != 'equal':
                        out.append((i1 + x1, i1 + x2, j1 + y1, j1 + y2))
            else:
                out.append((i1, i2, j1, j2))
            continue
        pi, pj = i1, j1
        for i, j in pairs:
            stack.append((pi, i, pj, j))
            pi, pj = i + 1, j + 1
        stack.append((pi, i2, pj, j2))
    out.sort()
    return out


def _resolve(bs, ms, ts, rep):
    """Zone modifiee des deux cotes : renvoie la liste d'evenements retenue."""
    if ms == ts:
        return ts
    if not bs and not (_ids(ms) & _ids(ts)):
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
    # les champs volatils locaux ne sont pas des modifications : on garde ceux de la base
    vol = {}
    for e, r in eb:
        if e in QUIET:
            vol.setdefault(e, []).append(r)
    seen = {}
    fixed = []
    for e, r in em:
        if e in QUIET:
            k = seen.get(e, 0)
            seen[e] = k + 1
            if k < len(vol.get(e, ())):
                r = vol[e][k]
        fixed.append((e, r))
    em = fixed
    if em == eb:
        rep['ok'] = True
        return theirs, rep
    em, renum = _deconflict(eb, em, et)
    rep['renumbered'] = renum
    hunks = []
    table = {}
    ident = lambda evs: [table.setdefault(x, len(table)) for x in evs]   # noqa: E731
    wtab = {}
    weak = lambda evs: [wtab.setdefault((e, r[:4]), len(wtab)) for e, r in evs]   # noqa: E731
    ib, wb = ident(eb), weak(eb)
    for side, ev in (('m', em), ('t', et)):
        hunks += [(i1, i2, side, j1, j2) for i1, i2, j1, j2 in _diff(ib, ident(ev), wb, weak(ev))]
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
    if res == et or _semantic(res) == _semantic(et):
        return theirs, rep
    rep['changed'] = True
    return _build(_head(theirs), res), rep


def keep_personal(data, local):
    """Remplace dans 'data' les reglages personnels (PERSONAL) par ceux de 'local'.
    Si 'local' en est depourvu, on garde ceux de 'data'."""
    try:
        mine = {}
        for e, r in events(local):
            if e in PERSONAL:
                mine.setdefault(e, []).append(r)
        seen, out, changed = {}, [], False
        for e, r in events(data):
            if e in PERSONAL and mine.get(e):
                k = seen.get(e, 0)
                seen[e] = k + 1
                if k < len(mine[e]) and mine[e][k] != r:
                    r, changed = mine[e][k], True
            out.append((e, r))
        return _build(_head(data), out) if changed else data
    except (ValueError, IndexError):
        return data


def same_content(a, b):
    """Deux versions du projet sont-elles identiques, horodatages et numeros de serie mis a part ?"""
    try:
        return a == b or _semantic(list(events(a))) == _semantic(list(events(b)))
    except (ValueError, IndexError):
        return False
