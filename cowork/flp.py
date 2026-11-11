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
