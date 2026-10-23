"""Gera orbit/ui/web/img/orbit-icon.ico a partir da geometria de orbit-logo.svg.

Dependência só de desenvolvimento (requirements-dev.txt). Uso: python tools/gerar_icone.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

SAIDA = Path(__file__).resolve().parent.parent / "orbit" / "ui" / "web" / "img" / "orbit-icon.ico"
S = 40  # fator de supersampling sobre o viewBox 100x100
FOLHA, DOBRA, LINHA, ORBITA = "#e4e8ee", "#93a0b0", "#1b2129", "#7fa7d9"
ANG = math.radians(-20)
CX, CY, RX, RY = 50, 52, 44, 14


def rot(x, y):
    """Aplica rotate(-20 50 52) do SVG."""
    dx, dy = x - CX, y - CY
    return (CX + dx * math.cos(ANG) - dy * math.sin(ANG), CY + dx * math.sin(ANG) + dy * math.cos(ANG))


def px(p):
    return (p[0] * S, p[1] * S)


def disco(d, x, y, r, cor):
    d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=cor)


def traco(d, pts, w, cor):
    # carimba discos ao longo do traço (pontas redondas, sem emendas)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] if len(pts) > 1 else pts):
        passos = max(1, int(math.dist((x0, y0), (x1, y1)) * S / 2))
        for i in range(passos + 1):
            t = i / passos
            disco(d, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, w / 2, cor)


def orbita(d, w=4.5, dash=20.3, gap=7.5):
    """Elipse tracejada (pontas redondas), no sistema local, depois girada."""
    n = 600
    pts = [(CX + RX * math.cos(2 * math.pi * i / n), CY + RY * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]
    ciclo, acc, atual = dash + gap, 0.0, []
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if acc % ciclo < dash:
            atual.append(rot(*a))
        elif atual:
            atual.append(rot(*a)); traco(d, atual, w, ORBITA); atual = []
        acc += seg
    if atual:
        traco(d, atual, w, ORBITA)


def arco(cx, cy, r, a0, a1, n=12):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def desenhar():
    img = Image.new("RGBA", (100 * S, 100 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    orbita(d)
    # folha: M37 22 h19 l12 12 v42 ... cantos de raio 3.5
    r = 3.5
    folha = arco(37, 25.5, r, 180, 270)
    folha += [(56, 22), (68, 34)]
    folha += arco(64.5, 76, r, 0, 90)
    folha += arco(37, 76, r, 90, 180)
    d.polygon([px(p) for p in folha], fill=FOLHA)
    dobra = [(56, 22), (56, 30.5)] + arco(59.5, 30.5, r, 180, 90) + [(68, 34)]
    d.polygon([px(p) for p in dobra], fill=DOBRA)
    traco(d, [(41, 49), (62, 49)], 4, LINHA)
    traco(d, [(41, 59), (56, 59)], 4, LINHA)
    # frente da órbita: só a metade y_local >= 52, recortada por máscara
    frente = Image.new("RGBA", img.size, (0, 0, 0, 0))
    orbita(ImageDraw.Draw(frente))
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon([px(rot(x, y)) for x, y in [(-100, 52), (200, 52), (200, 200), (-100, 200)]], fill=255)
    img.paste(frente, (0, 0), Image.composite(frente.split()[3], Image.new("L", img.size, 0), m))
    d = ImageDraw.Draw(img)
    sx, sy = rot(90, 46)
    disco(d, sx, sy, 6, ORBITA)
    return img


if __name__ == "__main__":
    base = desenhar().resize((256, 256), Image.LANCZOS)
    base.save(SAIDA, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print("gerado", SAIDA)
