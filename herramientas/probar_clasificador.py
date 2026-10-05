#!/usr/bin/env python3
"""Mide el clasificador por palabras clave sobre un CSV de frases etiquetadas.

    python3 herramientas/probar_clasificador.py                    # datos/frases_propias.csv
    python3 herramientas/probar_clasificador.py datos/otro.csv     # cualquier CSV con el mismo formato

Formato del CSV: frase,accion,objeto,color,prioridad,permitido  (permitido = 1 o 0)
No usa ROS ni red: corre en cualquier máquina con Python 3.
"""
import csv
import os
import sys
import time

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(RAIZ, 'src', 'parcial_g4'))
from parcial_g4.decision import clasificar_palabras_clave   # noqa: E402

CAMPOS = ['accion', 'objeto', 'color', 'prioridad', 'permitido']


def esperado(fila):
    return {'accion': fila['accion'].strip(), 'objeto': fila['objeto'].strip(),
            'color': fila['color'].strip(), 'prioridad': int(fila['prioridad']),
            'permitido': fila['permitido'].strip() in ('1', 'true', 'True', 'si')}


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, 'datos', 'frases_propias.csv')
    with open(ruta, newline='', encoding='utf-8') as f:
        filas = list(csv.DictReader(f))

    aciertos = {c: 0 for c in CAMPOS}
    completas, tiempos = 0, []
    print(f'{len(filas)} frases de {ruta}\n')
    print('FALLOS (campo: obtenido / esperado)')
    print('-' * 70)
    for fila in filas:
        t0 = time.perf_counter()
        obtenido = clasificar_palabras_clave(fila['frase'])
        tiempos.append((time.perf_counter() - t0) * 1000)
        meta = esperado(fila)
        malos = [c for c in CAMPOS if obtenido[c] != meta[c]]
        for c in CAMPOS:
            aciertos[c] += c not in malos
        completas += not malos
        if malos:
            detalle = ', '.join(f'{c}: {obtenido[c]} / {meta[c]}' for c in malos)
            print(f'"{fila["frase"]}"\n    {detalle}')

    n = len(filas)
    print('-' * 70)
    print('\nEXACTITUD POR CAMPO')
    for c in CAMPOS:
        print(f'  {c:10} {aciertos[c]:3}/{n}  = {100 * aciertos[c] / n:5.1f} %')
    print(f'  {"COMPLETA":10} {completas:3}/{n}  = {100 * completas / n:5.1f} %'
          '   (los 5 campos correctos a la vez)')
    tiempos.sort()
    print(f'\nTiempo por frase: mediana {tiempos[n // 2]:.3f} ms, '
          f'máximo {tiempos[-1]:.3f} ms')


if __name__ == '__main__':
    main()
