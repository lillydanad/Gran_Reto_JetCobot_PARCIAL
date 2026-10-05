#!/usr/bin/env python3
"""Diagnóstico de una posición de agarre (broker APAGADO).

    python3 herramientas/diagnostico_pose.py pos_rojo

Lleva el brazo a HOME -> observación -> pre-agarre -> la pose enseñada, igual que
el worker, y en cada tramo imprime cada 0,5 s los ángulos que REPORTA el brazo
frente a los PEDIDOS. Al final pregunta qué se vio, para saber si el problema es:
  A) la pose enseñada está mal (el brazo llega, pero la pinza no queda en el bloque), o
  B) el brazo no puede llegar a esa pose (se detiene antes), o
  C) el brazo llega pero reporta ángulos equivocados.
"""
import json
import math
import os
import sys
import time

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(RAIZ, 'src', 'arm_broker'))
from arm_broker import fk   # noqa: E402

VEL = 30


def fmt(v):
    return '[' + ', '.join(f'{a:7.1f}' for a in v) + ']'


def leer(mc):
    for _ in range(10):
        v = mc.get_angles()
        if isinstance(v, list) and len(v) == 6:
            return v
        time.sleep(0.1)
    return None


def tramo(mc, nombre, objetivo, segundos=20):
    print(f'\n--- {nombre}: pido {fmt(objetivo)}')
    mc.send_angles(objetivo, VEL)
    t0, previo, quieto = time.time(), None, 0.0
    while time.time() - t0 < segundos:
        time.sleep(0.5)
        q = leer(mc)
        if q is None:
            print('    (sin lectura)')
            continue
        falta = max(abs(a - b) for a, b in zip(q, objetivo))
        print(f'    t={time.time() - t0:4.1f}s  leo {fmt(q)}  falta máx {falta:5.1f}°')
        if falta < 3:
            print('    LLEGÓ')
            return q
        if previo and max(abs(a - b) for a, b in zip(q, previo)) < 0.3:
            quieto += 0.5
            if quieto >= 3:
                print('    SE DETUVO sin llegar')
                return q
        else:
            quieto = 0.0
        previo = q
    print('    se acabó el tiempo')
    return q


def main():
    nombre = sys.argv[1] if len(sys.argv) > 1 else 'pos_rojo'
    with open(os.path.join(RAIZ, 'datos', 'puntos_g4.json'), encoding='utf-8') as f:
        datos = json.load(f)
    p = datos['posiciones'][nombre]
    obs = datos['puntos']['observacion']['angulos']
    home = datos['puntos']['home']['angulos']
    agarre = p['angulos']
    arriba = [g + 0.3 * (o - g) for g, o in zip(agarre, obs)]
    print(f'{nombre}: ángulos enseñados {fmt(agarre)}')
    print(f'  FK RB-2 de lo enseñado: {fmt(fk.fk([math.radians(a) for a in agarre]))} mm')
    print(f'  coords que leyó el firmware al enseñar: {fmt(p["coords"][:3])} mm')

    from pymycobot.mycobot import MyCobot
    mc = MyCobot('/dev/ttyUSB0', 1000000)
    time.sleep(0.5)
    mc.power_on()
    try:
        mc.set_fresh_mode(1)
        print('fresh mode:', mc.get_fresh_mode())
    except Exception as e:          # noqa: BLE001
        print('fresh mode no disponible:', e)
    mc.set_gripper_value(100, 30)

    input('\nMano cerca del interruptor. Enter para empezar. ')
    tramo(mc, 'HOME', home)
    tramo(mc, 'OBSERVACIÓN', obs)
    tramo(mc, 'PRE-AGARRE (30 % hacia la observación)', arriba)
    q = tramo(mc, 'AGARRE (la pose enseñada)', agarre, segundos=30)
    print(f'\n  coords que reporta el firmware ahora: {mc.get_coords()}')
    if q:
        print(f'  FK RB-2 de lo leído: {fmt(fk.fk([math.radians(a) for a in q]))} mm')
    r = input('\n¿Dónde quedó la pinza?\n'
              '  a = rodeando el bloque (bien)\n'
              '  b = cerca, pero corrida (adelante/atrás/arriba): escribe "b" y cuántos cm y hacia dónde\n'
              '  c = lejos, claramente arriba del bloque\n> ')
    print(f'\nRespuesta: {r}')
    tramo(mc, 'PRE-AGARRE (subida)', arriba)
    tramo(mc, 'HOME', home)


if __name__ == '__main__':
    main()
