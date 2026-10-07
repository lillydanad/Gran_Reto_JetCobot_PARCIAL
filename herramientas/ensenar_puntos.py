#!/usr/bin/env python3
"""Paso 8a: calibración de puntos para el pick and place (Grupo 4).

SE CORRE CON EL BROKER APAGADO. Es preparación, no demostración: durante la demo
solo el worker del broker toca el brazo.

    python3 herramientas/ensenar_puntos.py                       # todo
    python3 herramientas/ensenar_puntos.py --puntos deposito_azul,deposito_verde
    python3 herramientas/ensenar_puntos.py --solo-camara         # solo la foto de calibración
    python3 herramientas/ensenar_puntos.py --solo-posiciones     # solo las 4 posiciones de agarre

Qué guarda en datos/puntos_g4.json:
  puntos     : home, observacion, seleccion y los 4 depósitos del nivel 5
               (coordenadas ya validadas), como ÁNGULOS reales leídos del brazo.
  posiciones : las 4 posiciones de agarre, enseñadas moviendo el brazo con el
               teclado (pasos de pocos mm), con sus ángulos, coordenadas y el
               píxel donde la cámara ve el bloque.
MoveIt planifica entre ángulos, así que guardar ángulos evita la diferencia de
13 a 24 mm entre el modelo de MoveIt y el firmware (medida en el Paso 6b).
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ARCHIVO = os.path.join(RAIZ, 'datos', 'puntos_g4.json')
FOTO = os.path.join(RAIZ, 'evidencias', 'calibracion_camara.jpg')
VELOCIDAD = 25            # regla del curso: nunca más de 50
POSE_HOME = [0, 0, 0, 0, 0, -45]

# Coordenadas del nivel 5 (firmware, validadas en su momento). COORDS_ROJO = la última definición.
COORDS_NIVEL5 = {
    'observacion': [172.1, -3.5, 261.9, -175.95, -0.68, -49.92],
    'seleccion': [52.0, 66.0, 408.7, -93.19, -44.34, 14.18],
    'deposito_rojo': [83.9, 245.6, 147.8, 174.31, 6.62, 40.58],
    'deposito_amarillo': [139.2, 230.0, 143.9, 178.85, 1.97, 26.86],
    'deposito_azul': [-44.8, 216.6, 130.9, -177.83, 0.41, 41.24],
    'deposito_verde': [18.0, 215.6, 137.5, -178.77, 0.26, 39.56],
}
# Orientación de agarre del nivel 5 (COORD_RECOGIDA): pinza apuntando hacia abajo
COORD_RECOGIDA = [225.4, -6.1, 131.4, 179.3, 5.11, -35.03]
Z_MINIMO = 80.0            # mm: más abajo la pinza toca la mesa
PASO_MAXIMO = 50.0         # mm o grados por comando
Z_AGARRE_NIVEL5 = 131.4    # altura de agarre que funcionó en el nivel 5
COLORES = ['rojo', 'verde', 'azul', 'amarillo']
FOTO_MASCARAS = os.path.join(RAIZ, 'evidencias', 'calibracion_mascaras.jpg')

sys.path.insert(0, os.path.join(RAIZ, 'src', 'parcial_g4'))
sys.path.insert(0, os.path.join(RAIZ, 'src', 'arm_broker'))


def preguntar(texto):
    r = input(f'\n>>> {texto}\n    [Enter = sí, s = saltar, q = salir] ').strip().lower()
    if r == 'q':
        print('Saliendo sin guardar lo que falta.')
        sys.exit(0)
    return r != 's'


def puerto_libre():
    r = subprocess.run(['fuser', '/dev/ttyUSB0'], capture_output=True, text=True)
    return not r.stdout.strip()


def leer(mc, funcion, intentos=10):
    for _ in range(intentos):
        v = funcion()
        if isinstance(v, list) and len(v) == 6:
            return [round(float(a), 2) for a in v]
        time.sleep(0.2)
    raise RuntimeError('el brazo no respondió; revisa el cable y la energía')


def esperar_quieto(mc, tope_s=10.0):
    """Espera a que el brazo deje de moverse (dos lecturas seguidas casi iguales)."""
    time.sleep(1.0)
    previo, fin = None, time.time() + tope_s
    while time.time() < fin:
        actual = leer(mc, mc.get_angles)
        if previo and max(abs(a - b) for a, b in zip(actual, previo)) < 0.5:
            return actual
        previo = actual
        time.sleep(0.4)
    return previo


def ir_angulos(mc, angulos):
    mc.send_angles(angulos, VELOCIDAD)
    return esperar_quieto(mc)


def ir_coords(mc, coords):
    mc.send_coords(coords, VELOCIDAD)
    return esperar_quieto(mc)


def registrar(mc):
    return {'angulos': leer(mc, mc.get_angles), 'coords': leer(mc, mc.get_coords)}


def medir_camara():
    import cv2
    from parcial_g4 import vision
    frame = vision.capturar()
    encontrados = vision.detectar(frame)
    os.makedirs(os.path.dirname(FOTO), exist_ok=True)
    cv2.imwrite(FOTO, vision.dibujar(frame, encontrados))
    cv2.imwrite(FOTO_MASCARAS, vision.mosaico_mascaras(frame))
    return {c: d['centro'] for c, d in encontrados.items()}


AYUDA = """
    Comandos (uno por línea, Enter para enviar):
      x 10   y -5   z -10   rz 15   mueve la punta (mm) o gira la pinza (grados); máx. 50 por comando
      abrir / cerrar                  prueba la pinza
      ok                              guarda ESTA pose como posición de agarre
      saltar                          sigue con el siguiente color sin guardar
    Objetivo: el bloque centrado ENTRE los dedos abiertos, la punta ~1 cm sobre la mesa."""


def revisar_pose(p):
    """Devuelve una lista de problemas de la pose enseñada (vacía = sirve)."""
    import math
    from arm_broker import fk
    problemas = []
    ok, razon = fk.dentro_de_limites([math.radians(a) for a in p['angulos']])
    if not ok:
        problemas.append(f'fuera de límites articulares: {razon}')
    z = p['coords'][2]
    if not 90 <= z <= 175:
        problemas.append(f'altura z = {z:.0f} mm, rara (en el nivel 5 se agarraba a {Z_AGARRE_NIVEL5:.0f} mm)')
    return problemas


def ensenar_a_mano(mc, color):
    """Se sueltan los motores, la persona lleva la pinza al bloque, y se bloquean ahí."""
    while True:
        mc.set_gripper_value(100, 30)
        time.sleep(1.5)
        input('    1) SOSTÉN EL BRAZO CON LAS DOS MANOS (una en el codo, otra cerca de la pinza).\n'
              '       Al presionar Enter los motores se sueltan y el brazo pesa. ')
        mc.release_all_servos()
        input(f'    2) Lleva la pinza al bloque {color.upper()}: los dedos abiertos A LOS LADOS del bloque,\n'
              '       la pinza lo más vertical posible, la punta ~1 cm sobre la mesa.\n'
              '       Mantén el brazo QUIETO ahí y presiona Enter (los motores se bloquean). ')
        mc.power_on()
        time.sleep(1.2)
        p = registrar(mc)
        problemas = revisar_pose(p)
        print(f'       pose leída: coords {p["coords"][:3]}  ángulos {p["angulos"]}')
        for pr in problemas:
            print(f'       OJO: {pr}')
        r = input('    3) Enter = probar el agarre · a = ajustar con el teclado · r = repetir · '
                  's = saltar este color: ').strip().lower()
        if r == 's':
            return None
        if r == 'r':
            ir_coords(mc, [p['coords'][0], p['coords'][1], p['coords'][2] + 60] + p['coords'][3:])
            continue
        if r == 'a':
            ajustada = ensenar_con_teclado(mc, color, p['coords'], mover_al_inicio=False)
            if ajustada is None:
                continue
            p = ajustada
        mc.set_gripper_value(10, 30)                     # prueba de agarre
        time.sleep(1.5)
        bien = input('    4) ¿La pinza cerrada sujeta bien el bloque? [Enter = sí, n = no] ').strip().lower()
        mc.set_gripper_value(100, 30)
        time.sleep(1.5)
        if bien == 'n':
            ir_coords(mc, [p['coords'][0], p['coords'][1], p['coords'][2] + 60] + p['coords'][3:])
            continue
        if revisar_pose(p):
            if input('       La pose tiene advertencias. ¿Guardarla igual? [s = sí] ').strip().lower() != 's':
                continue
        return p


def ensenar_con_teclado(mc, color, inicio, mover_al_inicio=True):
    objetivo = list(inicio)
    if mover_al_inicio:
        ir_coords(mc, objetivo)
    mc.set_gripper_value(100, 30)
    print(AYUDA)
    ejes = {'x': 0, 'y': 1, 'z': 2, 'rz': 5}
    while True:
        cmd = input(f'    [{color}] x={objetivo[0]:.0f} y={objetivo[1]:.0f} z={objetivo[2]:.0f} '
                    f'rz={objetivo[5]:.0f} > ').strip().lower()
        if cmd == 'ok':
            mc.set_gripper_value(100, 30)            # abierta antes de registrar y subir
            time.sleep(1.0)
            return registrar(mc)
        if cmd == 'saltar':
            return None
        if cmd in ('abrir', 'cerrar'):
            mc.set_gripper_value(100 if cmd == 'abrir' else 10, 30)
            time.sleep(1.5)
            continue
        partes = cmd.split()
        if len(partes) != 2 or partes[0] not in ejes:
            print(AYUDA)
            continue
        try:
            delta = float(partes[1])
        except ValueError:
            print('    número inválido')
            continue
        if abs(delta) > PASO_MAXIMO:
            print(f'    máximo {PASO_MAXIMO:.0f} por comando')
            continue
        nuevo = list(objetivo)
        nuevo[ejes[partes[0]]] += delta
        if nuevo[2] < Z_MINIMO:
            print(f'    z no puede bajar de {Z_MINIMO:.0f} mm (la pinza tocaría la mesa)')
            continue
        ir_coords(mc, nuevo)
        real = leer(mc, mc.get_coords)
        lejos = max(abs(a - b) for a, b in zip(real[:3], nuevo[:3]))
        if lejos > 10:
            print(f'    OJO: el brazo quedó en {real[:3]}, a {lejos:.0f} mm de lo pedido '
                  '(posición difícil de alcanzar). Prueba otro camino.')
        objetivo = nuevo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--solo-camara', action='store_true')
    ap.add_argument('--solo-posiciones', action='store_true')
    ap.add_argument('--puntos', default='', help='solo estos puntos del nivel 5, separados por coma')
    args = ap.parse_args()
    elegidos = [p.strip() for p in args.puntos.split(',') if p.strip()]

    if not puerto_libre():
        sys.exit('/dev/ttyUSB0 está ocupado. Corre ~/apagar_todo.sh y apaga los kernels de Jupyter.')

    datos = {'puntos': {}, 'posiciones': {}}
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, encoding='utf-8') as f:
            datos = json.load(f)

    from pymycobot.mycobot import MyCobot
    mc = MyCobot('/dev/ttyUSB0', 1000000)
    time.sleep(0.5)
    mc.power_on()
    time.sleep(0.5)
    print('Brazo conectado. Velocidad de todos los movimientos:', VELOCIDAD)

    def guardar():
        datos['actualizado'] = datetime.datetime.now().isoformat(timespec='seconds')
        with open(ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        print(f'    guardado en {ARCHIVO}')

    try:
        # 1. Puntos del nivel 5 -> ángulos reales
        if not (args.solo_camara or args.solo_posiciones):
            if preguntar('Mesa despejada alrededor del brazo. ¿Lo llevo a HOME?'):
                ir_angulos(mc, POSE_HOME)
                datos['puntos']['home'] = registrar(mc)
                guardar()
            for nombre, coords in COORDS_NIVEL5.items():
                if elegidos and nombre not in elegidos:
                    continue
                if not preguntar(f'¿Registro el punto "{nombre}" del nivel 5? (el brazo se moverá)'):
                    continue
                if nombre.startswith('deposito'):          # mismo camino que el nivel 5
                    ir_coords(mc, COORDS_NIVEL5['seleccion'])
                ir_coords(mc, coords)
                datos['puntos'][nombre] = registrar(mc)
                print(f'    {nombre}: ángulos {datos["puntos"][nombre]["angulos"]}')
                guardar()
                if nombre.startswith('deposito'):
                    ir_coords(mc, COORDS_NIVEL5['seleccion'])
                ir_angulos(mc, POSE_HOME)

        # 2. Vista de la cámara desde la pose de observación
        if not args.solo_posiciones and not elegidos and preguntar(
                'Pon los 4 bloques en sus posiciones de la mesa. ¿Voy a la pose de observación y tomo la foto?'):
            obs = datos['puntos'].get('observacion')
            if obs:
                ir_angulos(mc, obs['angulos'])
            else:
                ir_coords(mc, COORDS_NIVEL5['observacion'])
            centros = medir_camara()
            print(f'    la cámara ve: {centros}')
            print(f'    fotos: {FOTO} y {FOTO_MASCARAS}')
            faltan = [c for c in COLORES if c not in centros]
            if faltan:
                print(f'    OJO: no detecté {faltan}. Revisa la luz o la posición y repite con --solo-camara.')
            datos['camara'] = {'resolucion': [320, 240], 'centros': centros}
            guardar()
            ir_angulos(mc, POSE_HOME)

        # 3. Posiciones de agarre, con el teclado
        if not args.solo_camara and not elegidos:
            centros = datos.get('camara', {}).get('centros', {})
            for color in COLORES:
                if not preguntar(f'¿Enseño la posición donde está ahora el bloque {color.upper()}?'):
                    continue
                ir_angulos(mc, POSE_HOME)
                p = ensenar_a_mano(mc, color)
                if p is None:
                    ir_angulos(mc, POSE_HOME)
                    continue
                p['pixel'] = centros.get(color)
                p['color_en_calibracion'] = color
                datos['posiciones'][f'pos_{color}'] = p
                print(f'    pos_{color}: ángulos {p["angulos"]}  coords {p["coords"][:3]}  píxel {p["pixel"]}')
                guardar()
                arriba = list(p['coords'])
                arriba[2] += 60                            # sube 6 cm antes de volver
                ir_coords(mc, arriba)
                ir_angulos(mc, POSE_HOME)
    finally:
        print('\nFin. El brazo queda con los motores activos.')

    print('\nRESUMEN')
    for k, v in datos.get('puntos', {}).items():
        print(f'  punto    {k:18} {v["angulos"]}')
    for k, v in datos.get('posiciones', {}).items():
        print(f'  posición {k:18} {v["angulos"]}  píxel {v.get("pixel")}')


if __name__ == '__main__':
    main()
