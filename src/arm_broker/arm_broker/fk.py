"""Cinemática directa del JetCobot (MyCobot 280) — ítem 1."""

import math

JOINT_NAMES = ['1_Joint', '2_Joint', '3_Joint', '4_Joint', '5_Joint', '6_Joint']

# ============================== IMPLEMENTAR · ítem 1 ==============================
# Tabla DH del JetCobot: una fila (alpha_rad, a_mm, d_mm, theta_offset_rad) por
# articulación, en convención DH estándar. Dedúzcanla y verifíquenla con
# herramientas/verificar_fk.py contra el robot: criterio ≤ 10 mm.
# Tabla DH del JetCobot: una fila (alpha_rad, a_mm, d_mm, theta_offset_rad) por
# articulación, en convención DH estándar. Dedúzcanla y verifíquenla con
# herramientas/verificar_fk.py contra el robot: criterio ≤ 10 mm.
DH = [
    (math.pi / 2, 0.0, 134.75, 0.0),
    (0.0, -110.0, 0.0, -math.pi / 2),
    (0.0, -96.0, 0.0, 0.0),
    (math.pi / 2, 0.0, 63.4, -math.pi / 2),
    (-math.pi / 2, 0.0, 75.05, math.pi / 2),
    (0.0, 0.0, 50.0, 0.0)
]
# ===================================================================================

JOINT_LIMITS = [
    (-2.93, 2.93),
    (-2.36, 2.36),
    (-2.53, 2.53),
    (-2.58, 2.58),
    (-2.93, 2.93),
    (-3.14, 3.14),
]

ALCANCE_MIN_MM = 80.0
ALCANCE_MAX_MM = 480.0

def _t(alpha, a, d, theta):
    ca, sa = math.cos(alpha), math.sin(alpha)
    ct, st = math.cos(theta), math.sin(theta)
    
    # Matriz corregida a convención Denavit-Hartenberg Estándar
    return [
        [ct, -st * ca,  st * sa, a * ct],
        [st,  ct * ca, -ct * sa, a * st],
        [0.0,      sa,       ca,      d],
        [0.0,     0.0,      0.0,    1.0],
    ]


def _mul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def fk_matriz(q):
    """Matriz homogénea 4x4 de la base al efector final."""
    T = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    for (alpha, a, d, off), theta in zip(DH, q):
        T = _mul(T, _t(alpha, a, d, theta + off))
    return T


def fk(angulos):
    """Calcula y extrae la coordenada espacial (x, y, z) final en mm."""
    matriz_homogenea = fk_matriz(angulos)
    eje_x = matriz_homogenea[0][3]
    eje_y = matriz_homogenea[1][3]
    eje_z = matriz_homogenea[2][3]
    return (eje_x, eje_y, eje_z)
# =================================================================================


def dentro_de_limites(q):
    if len(q) != 6:
        return False, f'se esperaban 6 ángulos, llegaron {len(q)}'
    for i, (valor, (lo, hi)) in enumerate(zip(q, JOINT_LIMITS)):
        if not lo <= valor <= hi:
            return False, f'{JOINT_NAMES[i]} fuera de rango: {valor:.3f} rad, límite [{lo}, {hi}]'
    return True, ''


def dentro_del_workspace(q):
    x, y, z = fk(q)
    r = math.sqrt(x * x + y * y + z * z)
    if r > ALCANCE_MAX_MM:
        return False, f'efector a {r:.0f} mm de la base, máximo {ALCANCE_MAX_MM:.0f}'
    if r < ALCANCE_MIN_MM:
        return False, f'efector a {r:.0f} mm de la base, demasiado cerca'
    if z < 0.0:
        return False, f'z = {z:.0f} mm: el efector quedaría bajo la base'
    return True, ''


def paso_articular(q_desde, q_hasta):
    return max(abs(b - a) for a, b in zip(q_desde, q_hasta))
