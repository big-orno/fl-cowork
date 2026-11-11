"""Genere le logo de FL Cowork (cowork/icon.png, cowork/icon.ico) sans dependance externe.

Deux anneaux qui se chevauchent sur une pastille sombre : deux producteurs, un projet.
Usage : py -3.14 tools/make_icon.py
"""
import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cowork')
BG, BG2 = (28, 31, 38), (18, 20, 24)
ORANGE, SKY = (255, 138, 61), (88, 196, 255)
SS = 3


def sdf_round_rect(x, y, half, r):
    qx, qy = abs(x) - (half - r), abs(y) - (half - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def render(size):
    px = []
    c = size / 2
    unit = size / 256
    ra, thick = 62 * unit, 17 * unit
    ax, bx = c - 36 * unit, c + 36 * unit
    for j in range(size):
        row = bytearray()
        for i in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sj in range(SS):
                for si in range(SS):
                    x = i + (si + .5) / SS - c
                    y = j + (sj + .5) / SS - c
                    d = sdf_round_rect(x, y, c - unit * 6, unit * 52)
                    if d > 0:
                        continue
                    t = (y + c) / size
                    col = [BG[k] * (1 - t) + BG2[k] * t for k in range(3)]
                    da = abs(math.hypot(x - (ax - c), y) - ra) - thick / 2
                    db = abs(math.hypot(x - (bx - c), y) - ra) - thick / 2
                    ina = math.hypot(x - (ax - c), y) < ra
                    inb = math.hypot(x - (bx - c), y) < ra
                    if ina and inb:
                        col = [col[k] * .55 + 255 * .45 for k in range(3)]
                    if da < 0 and db < 0:
                        col = (255, 255, 255)
                    elif da < 0:
                        col = ORANGE
                    elif db < 0:
                        col = SKY
                    acc[0] += col[0]; acc[1] += col[1]; acc[2] += col[2]; acc[3] += 1
            n = SS * SS
            a = acc[3]
            if a:
                row += bytes((int(acc[0] / a), int(acc[1] / a), int(acc[2] / a), int(255 * a / n)))
            else:
                row += bytes(4)
        px.append(bytes(row))
    return px


def png(px, size):
    raw = b''.join(b'\x00' + r for r in px)

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def main():
    big = png(render(256), 256)
    small = png(render(64), 64)
    with open(os.path.join(OUT, 'icon.png'), 'wb') as f:
        f.write(small)
    sizes = [(256, big), (48, png(render(48), 48)), (32, png(render(32), 32)), (16, png(render(16), 16))]
    ico = struct.pack('<HHH', 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    body = b''
    for s, data in sizes:
        ico += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(data), off + len(body))
        body += data
    with open(os.path.join(OUT, 'icon.ico'), 'wb') as f:
        f.write(ico + body)
    print('ok')


if __name__ == '__main__':
    main()
