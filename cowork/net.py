"""Transport reseau : trames, chiffrement TLS-PSK, codes de session."""
import base64
import hashlib
import json
import os
import socket
import ssl
import struct

HUB_PORT = 47810
BRIDGE_PORT = int(os.environ.get('FLCOWORK_BRIDGE_PORT', 47800))
MAX_FRAME = 16 * 1024 * 1024
CHUNK = 256 * 1024
_CIPHERS = ('ECDHE-PSK-CHACHA20-POLY1305:ECDHE-PSK-AES256-CBC-SHA384:'
            'DHE-PSK-AES256-GCM-SHA384:PSK-AES256-GCM-SHA384')


def psk_context(server, key):
    """Contexte TLS 1.2 a cle pre-partagee : chiffre et authentifie sans certificat."""
    psk = hashlib.sha256(b'flcowork' + key).digest()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(_CIPHERS)
    if server:
        ctx.set_psk_server_callback(lambda ident: psk, 'flc')
    else:
        ctx.set_psk_client_callback(lambda hint: ('flc', psk))
    return ctx


def pack(obj, data=b''):
    head = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    return struct.pack('>IH', 2 + len(head) + len(data), len(head)) + head + data


async def read_frame(reader):
    raw = await reader.readexactly(4)
    (n,) = struct.unpack('>I', raw)
    if n < 2 or n > MAX_FRAME:
        raise ValueError('trame invalide')
    body = await reader.readexactly(n)
    (hl,) = struct.unpack('>H', body[:2])
    return json.loads(body[2:2 + hl].decode('utf-8')), body[2 + hl:]


def new_key():
    return os.urandom(10)


def make_code(ip, port, key):
    raw = socket.inet_aton(ip) + struct.pack('>H', port) + key
    b = base64.b32encode(raw).decode('ascii').rstrip('=')
    return 'FLC-' + '-'.join(b[i:i + 5] for i in range(0, len(b), 5))


def parse_code(code):
    b = ''.join(c for c in code.upper().replace('FLC-', '', 1) if c.isalnum())
    raw = base64.b32decode(b + '=' * (-len(b) % 8))
    if len(raw) != 16:
        raise ValueError('code de session invalide')
    return socket.inet_ntoa(raw[:4]), struct.unpack('>H', raw[4:6])[0], raw[6:]


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


def vpn_ips():
    """Adresses des reseaux prives virtuels (Radmin 26.x, Hamachi 25.x, Tailscale/CGNAT 100.64/10)."""
    out = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return out
    for i in infos:
        ip = i[4][0]
        a, b = (int(x) for x in ip.split('.')[:2])
        if (a in (25, 26) or (a == 100 and 64 <= b <= 127)) and ip not in out:
            out.append(ip)
    return out


def sha_file(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
