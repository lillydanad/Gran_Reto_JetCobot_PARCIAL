"""Visión del parcial (Grupo 4): detectar los 4 bloques desde la pose de observación.

Lo usan herramientas/ensenar_puntos.py (calibración) y el worker del broker (demo),
para que ambos vean los colores EXACTAMENTE igual.

Rangos HSV estándar de OpenCV (H 0-180, S y V 0-255). El rojo da la vuelta al
círculo de color, por eso tiene dos tramos. La saturación mínima deja fuera el
fondo blanco y las líneas negras de la mesa.
"""
import time

import cv2
import numpy as np

RANGOS_HSV = {
    'rojo':     [((0, 100, 70), (10, 255, 255)), ((170, 100, 70), (180, 255, 255))],
    'amarillo': [((18, 100, 100), (35, 255, 255))],
    'verde':    [((40, 60, 40), (85, 255, 255))],
    'azul':     [((95, 100, 40), (130, 255, 255))],
}
ANCHO, ALTO = 320, 240
AREA_MINIMA = 600          # píxeles, en 320x240: descarta las etiquetas pequeñas de los bloques


def capturar(indice=0, descartar=15):
    """Toma una foto 320x240. Descarta los primeros cuadros mientras la cámara ajusta la exposición."""
    cap = cv2.VideoCapture(indice)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
    frame = None
    for _ in range(descartar):
        ok, f = cap.read()
        if ok:
            frame = f
        time.sleep(0.03)
    cap.release()
    if frame is None:
        raise RuntimeError('la cámara no entregó imagen (¿la tiene abierta otro programa?)')
    if frame.shape[1] != ANCHO:
        frame = cv2.resize(frame, (ANCHO, ALTO))
    return frame


def mascara(hsv, color):
    m = None
    for lo, hi in RANGOS_HSV[color]:
        parte = cv2.inRange(hsv, np.array(lo), np.array(hi))
        m = parte if m is None else cv2.bitwise_or(m, parte)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))   # quita puntitos


def detectar(frame):
    """{color: {'centro': [cx, cy], 'area': a, 'caja': [x, y, w, h]}} del contorno más grande de cada color."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    encontrados = {}
    for color in RANGOS_HSV:
        contornos, _ = cv2.findContours(mascara(hsv, color), cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        grandes = [c for c in contornos if cv2.contourArea(c) > AREA_MINIMA]
        if not grandes:
            continue
        c = max(grandes, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        encontrados[color] = {'centro': [x + w // 2, y + h // 2],
                              'area': int(cv2.contourArea(c)), 'caja': [x, y, w, h]}
    return encontrados


def dibujar(frame, encontrados):
    img = frame.copy()
    for color, d in encontrados.items():
        x, y, w, h = d['caja']
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255), 2)
        cv2.circle(img, tuple(d['centro']), 4, (0, 0, 0), -1)
        cv2.putText(img, color, (x, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2)
    return img


def mosaico_mascaras(frame):
    """Las 4 máscaras en una sola imagen 2x2: blanco = lo que se reconoce como ese color."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    celdas = []
    for color in RANGOS_HSV:
        m = cv2.cvtColor(mascara(hsv, color), cv2.COLOR_GRAY2BGR)
        cv2.putText(m, color, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        celdas.append(m)
    return np.vstack([np.hstack(celdas[:2]), np.hstack(celdas[2:])])
