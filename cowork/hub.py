"""Hub de session : tourne chez l'hote, ordonne et relaie tout.

- ops temps reel : le hub attribue un numero de sequence par operation et
  rediffuse a tous (l'emetteur s'en sert d'accuse de reception) ; le dernier
  ecrivain gagne, et tout le monde converge vers la meme valeur ;
- revisions du projet (.flp + samples) : stockees par empreinte SHA-1 ;
- stylo : un seul participant a la fois publie les changements de structure.
"""
import asyncio
import os
import time
import zlib

from . import net

COLORS = ['#ff8a3d', '#4cc2ff', '#7ee081', '#ff6b9d', '#c79bff', '#ffd84c', '#5ee0d0', '#ff7a6b']
TRANSIENT = ('tp', 'ts')


class Peer:
    def __init__(self, pid, writer):
        self.id = pid
        self.writer = writer
        self.name = '?'
        self.color = COLORS[(pid - 1) % len(COLORS)]
        self.pres = {}
        self.q = asyncio.Queue()
        self.task = None

    def info(self):
        return {'id': self.id, 'name': self.name, 'color': self.color, 'pres': self.pres}


class Hub:
    def __init__(self, key, blobdir, port=net.HUB_PORT, project=''):
        self.key = key
        self.blobdir = blobdir
        self.port = port
        self.project = project
        self.peers = {}
        self.next_id = 1
        self.ops = {}
        self.seq = 0
        self.rev = None
        self.baton = None
        self.muted = set()
        self.pending = {}      # pid -> manifeste en attente de blobs
        self.server = None
        os.makedirs(blobdir, exist_ok=True)

    async def start(self):
        ctx = net.psk_context(True, self.key)
        last = None
        for port in range(self.port, self.port + 20):
            try:
                self.server = await asyncio.start_server(self.on_conn, '0.0.0.0', port, ssl=ctx)
                self.port = port
                return
            except OSError as e:
                last = e
        raise last

    async def stop(self):
        if self.server:
            self.server.close()
        for p in list(self.peers.values()):
            p.writer.close()

    def blob(self, sha):
        return os.path.join(self.blobdir, sha)

    def send(self, peer, obj, data=b''):
        peer.q.put_nowait(net.pack(obj, data))

    def cast(self, obj, skip=None):
        frame = net.pack(obj)
        for p in self.peers.values():
            if p.id != skip:
                p.q.put_nowait(frame)

    async def writer_loop(self, peer):
        try:
            while True:
                frame = await peer.q.get()
                peer.writer.write(frame)
                await peer.writer.drain()
        except Exception:
            peer.writer.close()

    async def on_conn(self, reader, writer):
        peer = None
        try:
            hello, _ = await asyncio.wait_for(net.read_frame(reader), 10)
            if hello.get('t') != 'hello':
                return
            peer = Peer(self.next_id, writer)
            self.next_id += 1
            peer.name = str(hello.get('name') or 'Invite')[:32]
            self.peers[peer.id] = peer
            peer.task = asyncio.ensure_future(self.writer_loop(peer))
            if self.baton not in self.peers:
                self.baton = peer.id
            self.send(peer, {
                't': 'welcome', 'id': peer.id, 'project': self.project,
                'peers': [p.info() for p in self.peers.values()],
                'rev': self.rev, 'baton': self.baton, 'muted': sorted(self.muted),
                'ops': [[k, v, s] for k, (v, s) in self.ops.items()],
            })
            self.cast({'t': 'join', 'peer': peer.info()}, skip=peer.id)
            while True:
                msg, data = await net.read_frame(reader)
                await self.handle(peer, msg, data)
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, OSError, ValueError):
            pass
        finally:
            writer.close()
            if peer:
                self.peers.pop(peer.id, None)
                self.pending.pop(peer.id, None)
                if peer.task:
                    peer.task.cancel()
                self.cast({'t': 'leave', 'id': peer.id})
                if self.baton == peer.id:
                    self.baton = min(self.peers) if self.peers else None
                    self.cast({'t': 'baton', 'holder': self.baton})

    async def handle(self, peer, msg, data):
        t = msg.get('t')
        if t == 'ops':
            out = []
            for k, v in msg.get('o', ()):
                if k in self.muted:
                    continue
                self.seq += 1
                if k not in TRANSIENT:
                    self.ops[k] = (v, self.seq)
                out.append([k, v, self.seq])
            if out:
                self.cast({'t': 'ops', 'from': peer.id, 'o': out})
        elif t == 'pres':
            peer.pres = msg.get('p') or {}
            self.cast({'t': 'pres', 'id': peer.id, 'p': peer.pres}, skip=peer.id)
        elif t == 'chat':
            self.cast({'t': 'chat', 'from': peer.id, 'name': peer.name, 'color': peer.color,
                       'text': str(msg.get('text', ''))[:2000], 'time': time.time()})
        elif t == 'name':
            peer.name = str(msg.get('name') or peer.name)[:32]
            self.cast({'t': 'join', 'peer': peer.info()})
        elif t == 'mute':
            k = msg.get('k')
            if isinstance(k, str) and k not in self.muted:
                self.muted.add(k)
                self.ops.pop(k, None)
                self.cast({'t': 'mute', 'k': k})
        elif t == 'baton_req':
            self.cast({'t': 'baton_req', 'from': peer.id, 'name': peer.name})
        elif t == 'baton_give':
            to = msg.get('to')
            if peer.id == self.baton and to in self.peers:
                self.baton = to
                self.cast({'t': 'baton', 'holder': to})
        elif t == 'fp':
            if peer.id == self.baton and self.rev and msg.get('n') == self.rev['n']:
                self.rev['fp'] = msg.get('fp')
                self.rev['sig'] = msg.get('sig')
                self.cast({'t': 'rev', 'rev': self.rev})
        elif t == 'publish':
            if peer.id != self.baton:
                self.send(peer, {'t': 'error', 'msg': 'Seul le détenteur du stylo peut publier.'})
                return
            man = msg['manifest']
            self.pending[peer.id] = man
            need = sorted({f[2] for f in man['files'] if not os.path.exists(self.blob(f[2]))})
            if need:
                self.send(peer, {'t': 'need', 'shas': need})
            else:
                self.commit(peer)
        elif t == 'blob':
            await self.on_blob(peer, msg, data)
        elif t == 'get':
            asyncio.ensure_future(self.stream_blob(peer, str(msg.get('sha'))))

    def commit(self, peer):
        man = self.pending.pop(peer.id, None)
        if not man or peer.id != self.baton:
            return
        n = (self.rev['n'] if self.rev else 0) + 1
        self.rev = {'n': n, 'author': peer.id, 'author_name': peer.name, 'time': time.time(),
                    'flp': man['flp'], 'files': man['files'], 'fp': man.get('fp'),
                    'sig': man.get('sig'), 'samples': man.get('samples') or []}
        self.ops.clear()
        self.muted.clear()
        self.cast({'t': 'rev', 'rev': self.rev})

    async def on_blob(self, peer, msg, data):
        sha = str(msg.get('sha'))
        if not sha.isalnum():
            return
        tmp = self.blob(sha) + '.part%d' % peer.id
        with open(tmp, 'ab' if msg.get('off') else 'wb') as f:
            f.write(zlib.decompress(data))
        if msg.get('last'):
            loop = asyncio.get_running_loop()
            ok = await loop.run_in_executor(None, net.sha_file, tmp) == sha
            if ok:
                os.replace(tmp, self.blob(sha))
            else:
                os.remove(tmp)
            man = self.pending.get(peer.id)
            if man and all(os.path.exists(self.blob(f[2])) for f in man['files']):
                self.commit(peer)

    async def stream_blob(self, peer, sha):
        path = self.blob(sha)
        if not sha.isalnum() or not os.path.exists(path):
            self.send(peer, {'t': 'blob', 'sha': sha, 'missing': 1, 'last': 1})
            return
        size = os.path.getsize(path)
        off = 0
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(net.CHUNK)
                last = off + len(chunk) >= size
                self.send(peer, {'t': 'blob', 'sha': sha, 'off': off, 'size': size, 'last': int(last)},
                          zlib.compress(chunk, 1))
                off += len(chunk)
                if last:
                    break
                while peer.q.qsize() > 4:
                    await asyncio.sleep(0.005)
                    if peer.id not in self.peers:
                        return
