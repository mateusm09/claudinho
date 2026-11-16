#!/usr/bin/env python3
"""Gera o sprite do Claudinho (pixel art original) para o firmware.

Saídas:
  firmware/src/mascot.h        quadros como índices de paleta (1 byte/pixel)
  assets/mascot-preview.png    folha com todos os quadros, para revisão

Uso: python3 tools/mascot.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W, H = 16, 14  # canvas de cada quadro (com folga para pulo, "!" e "z")

# índice → (nome, RGB). 0 = transparente.
PALETTE = [
    ("clear", None),
    ("body", 0xD97757),
    ("eye", 0x1A1A1A),
    ("shade", 0xB85F42),
    ("amber", 0xF5A623),
    ("green", 0x30A46C),
    ("red", 0xE5484D),
    ("white", 0xF2F2F2),
]
C = {name: i for i, (name, _) in enumerate(PALETTE)}

# Corpo base 12x9 (sem olhos), desenhado no canvas a partir de (2, top).
#   o = corpo, s = sombra, . = vazio, A/B = pernas (alternam no "andar")
BODY = [
    "..oooooooooo..",
    "..oooooooooo..",
    "..oooooooooo..",
    "oooooooooooooo",
    "oooooooooooooo",
    "..oooooooooo..",
    "..ssssssssss..",
    "..A.B....A.B..",
    "..A.B....A.B..",
]
BODY_X = 1  # o corpo tem 14 de largura; centraliza no canvas de 16


def blank():
    return [[0] * W for _ in range(H)]


def put(g, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        g[y][x] = c


def body(g, top, legs="both", arms="side"):
    for r, row in enumerate(BODY):
        for col, ch in enumerate(row):
            x, y = BODY_X + col, top + r
            if ch == "o":
                # bracinhos (colunas 0-1 e 12-13 nas linhas 3-4): só se arms == "side"
                if col in (0, 1, 12, 13) and arms != "side":
                    continue
                put(g, x, y, C["body"])
            elif ch == "s":
                put(g, x, y, C["shade"])
            elif ch == "A" and legs in ("both", "A"):
                put(g, x, y, C["body"])
            elif ch == "B" and legs in ("both", "B"):
                put(g, x, y, C["body"])
    if arms == "up":  # acenando: braços erguidos ao lado da cabeça
        for (x, y) in ((1, top), (2, top + 1), (14, top), (13, top + 1)):
            put(g, BODY_X + x - 1, y, C["body"])
    if arms == "wave":  # só o braço direito erguido
        for col in (0, 1):
            put(g, BODY_X + col, top + 3, C["body"])
            put(g, BODY_X + col, top + 4, C["body"])
        put(g, BODY_X + 13, top, C["body"])
        put(g, BODY_X + 12, top + 1, C["body"])


# Olhos: posições relativas ao corpo (colunas 4 e 9, linha 1-2 do corpo)
EYE_L, EYE_R = BODY_X + 4, BODY_X + 9


def eyes(g, top, kind="open"):
    e = C["eye"]
    if kind == "open":
        for x in (EYE_L, EYE_R):
            put(g, x, top + 1, e)
            put(g, x, top + 2, e)
    elif kind == "closed":
        for x in (EYE_L, EYE_R):
            put(g, x - 1, top + 2, e)
            put(g, x, top + 2, e)
    elif kind == "happy":  # ^ ^
        for x in (EYE_L, EYE_R):
            put(g, x - 1, top + 2, e)
            put(g, x, top + 1, e)
            put(g, x + 1, top + 2, e)
    elif kind == "x":
        for x in (EYE_L, EYE_R):
            put(g, x - 1, top + 1, e)
            put(g, x + 1, top + 1, e)
            put(g, x, top + 2, e)
            put(g, x - 1, top + 3, e)
            put(g, x + 1, top + 3, e)
    elif kind == "up":  # olhando para cima (esperando)
        for x in (EYE_L, EYE_R):
            put(g, x, top + 0, e)
            put(g, x, top + 1, e)


def frame(top=4, legs="both", arms="side", eye="open", extra=None):
    g = blank()
    body(g, top, legs, arms)
    eyes(g, top, eye)
    if extra:
        extra(g, top)
    return g


def bang(color):
    def f(g, top):  # "!" à esquerda (o braço que acena fica à direita)
        x = 1
        for y in range(top - 4, top - 1):
            put(g, x, y, color)
        put(g, x, top, color)
    return f


def sparkles(phase):
    def f(g, top):
        pts = [(0, top - 3), (15, top - 2), (1, top + 6), (14, top + 7)]
        for i, (x, y) in enumerate(pts):
            if (i + phase) % 2 == 0:
                put(g, x, y, C["green"])
                put(g, x, y - 1, C["white"]) if y - 1 >= 0 and i == phase % 4 else None
    return f


Z_GLYPH = ["####", "..#.", ".#..", "####"]  # "Z" 4x4 com diagonal legível


def zzz(step):
    def f(g, top):
        # "Z" pisca acima da cabeça (as 4 linhas acima do corpo cabem exatamente)
        if step in (0, 1):
            x0 = 11 if step == 0 else 12
            for dy, row in enumerate(Z_GLYPH):
                for dx, ch in enumerate(row):
                    if ch == "#":
                        put(g, x0 + dx, top - 4 + dy, C["white"])
    return f


def red_mark(g, top):
    put(g, 14, top - 3, C["red"])
    put(g, 14, top - 2, C["red"])
    put(g, 14, top, C["red"])


ANIMS: dict[str, tuple[int, list]] = {
    # nome: (ms por quadro, quadros)
    "idle": (180, [frame()] * 14 + [frame(eye="closed")] + [frame()] * 6 + [frame(eye="closed")]),
    "working": (110, [
        frame(top=4, legs="A"), frame(top=3, legs="both"),
        frame(top=4, legs="B"), frame(top=3, legs="both"),
    ]),
    "waiting": (200, [
        frame(arms="wave", eye="up", extra=bang(C["amber"])),
        frame(arms="side", eye="up", extra=bang(C["amber"])),
        frame(arms="wave", eye="up"),
        frame(arms="side", eye="up", extra=bang(C["amber"])),
    ]),
    "done": (160, [
        frame(top=4, eye="happy", extra=sparkles(0)),
        frame(top=2, arms="up", eye="happy", extra=sparkles(1)),
        frame(top=4, eye="happy", extra=sparkles(2)),
        frame(top=4, eye="happy", extra=sparkles(3)),
    ]),
    "error": (300, [
        frame(eye="x", extra=red_mark),
        frame(eye="x"),
    ]),
    "sleep": (450, [frame(eye="closed", extra=zzz(i)) for i in range(3)] + [frame(eye="closed")]),
}
# ordem tem que bater com o enum MascotAnim do firmware
ANIM_ORDER = ["idle", "working", "waiting", "done", "error", "sleep"]


def write_header(path: Path) -> None:
    frames, index = [], []
    for name in ANIM_ORDER:
        ms, fs = ANIMS[name]
        index.append((name, len(frames), len(fs), ms))
        frames.extend(fs)
    out = [
        "// GERADO por tools/mascot.py, não edite à mão.",
        "#pragma once",
        "#include <stdint.h>",
        "",
        f"namespace mascot {{",
        f"constexpr int W = {W}, H = {H};",
        f"constexpr int FRAME_COUNT = {len(frames)};",
        "",
        "// RGB888 por índice; 0 = transparente",
        "constexpr uint32_t PALETTE[] = {" + ", ".join(f"0x{rgb or 0:06X}" for _, rgb in PALETTE) + "};",
        "",
        "enum Anim : uint8_t { " + ", ".join(f"A_{n.upper()}" for n in ANIM_ORDER) + ", A_COUNT };",
        "struct AnimInfo { uint16_t first, count, ms; };",
        "constexpr AnimInfo ANIMS[A_COUNT] = {",
        *[f"  {{{first}, {count}, {ms}}},  // {name}" for name, first, count, ms in index],
        "};",
        "",
        f"constexpr uint8_t FRAMES[FRAME_COUNT][H][W] = {{",
    ]
    for i, g in enumerate(frames):
        out.append(f"  {{  // {i}")
        for row in g:
            out.append("    {" + ",".join(str(v) for v in row) + "},")
        out.append("  },")
    out += ["};", "}  // namespace mascot", ""]
    path.write_text("\n".join(out))


def write_preview(path: Path, scale: int = 8, gap: int = 2) -> None:
    """Folha: uma linha por animação, quadros lado a lado (PNG puro, sem dependências)."""
    rows = [ANIMS[n][1] for n in ANIM_ORDER]
    cols = max(len(r) for r in rows)
    cw, ch = W * scale + gap * scale, H * scale + gap * scale
    pw, ph = cols * cw, len(rows) * ch
    bg = (0x14, 0x14, 0x14)
    px = [[bg] * pw for _ in range(ph)]
    for r, fs in enumerate(rows):
        for c, g in enumerate(fs):
            for y in range(H):
                for x in range(W):
                    rgb = PALETTE[g[y][x]][1]
                    if rgb is None:
                        continue
                    col = ((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)
                    for dy in range(scale):
                        for dx in range(scale):
                            px[r * ch + y * scale + dy][c * cw + x * scale + dx] = col
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", pw, ph, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    (ROOT / "assets").mkdir(exist_ok=True)
    write_header(ROOT / "firmware/src/mascot.h")
    write_preview(ROOT / "assets/mascot-preview.png")
    total = sum(len(ANIMS[n][1]) for n in ANIM_ORDER)
    print(f"{total} quadros, {total * W * H} bytes → firmware/src/mascot.h, assets/mascot-preview.png")
