#!/usr/bin/env python3
"""Exactitud de LAYA vs clasificador por palabras clave, campo por campo.

    python3 herramientas/evaluar_laya.py
    python3 herramientas/evaluar_laya.py --csv datos/frases_profe.csv --salida datos/p1_evaluacion_laya.csv

Por cada frase hace UNA petición a LAYA con las preguntas de decision.py más las
dos preguntas sí/no de peligro (v4 y v5 de comparar_seguridad.py), y guarda en un
CSV la decisión de cada método y la probabilidad de peligro. Ese CSV es el
entregable de la P1 ("las frases y la decisión obtenida por cada método").
Corre en el Jetson. No usa ROS.
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.request

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(RAIZ, 'src', 'parcial_g4'))
sys.path.insert(0, os.path.join(RAIZ, 'herramientas'))
from parcial_g4.decision import (preguntas_laya, decision_desde_laya,   # noqa: E402
                                 clasificar_palabras_clave)
from comparar_seguridad import PREGUNTAS as PREG_SEGURIDAD               # noqa: E402

CAMPOS = ['accion', 'objeto', 'color', 'prioridad', 'permitido']
EXTRA = {k: v for k, v in PREG_SEGURIDAD.items() if k == 'v4_noul' or k.startswith('v5_')}


def esperado(fila):
    return {'accion': fila['accion'].strip(), 'objeto': fila['objeto'].strip(),
            'color': fila['color'].strip(), 'prioridad': int(fila['prioridad']),
            'permitido': fila['permitido'].strip() in ('1', 'true', 'True', 'si')}


def consultar(url, frase):
    preguntas = dict(preguntas_laya(), **EXTRA)
    cuerpo = json.dumps({'state': {'body': frase}, 'model': 'multilingual',
                         'questions': preguntas}).encode()
    req = urllib.request.Request(url, data=cuerpo, headers={'Content-Type': 'application/json'})
    t0 = time.perf_counter()
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return resp, (time.perf_counter() - t0) * 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://172.51.9.2:5000/v1/systemone')
    ap.add_argument('--csv', default=os.path.join(RAIZ, 'datos', 'frases_propias.csv'))
    ap.add_argument('--salida', default=os.path.join(RAIZ, 'evidencias', 'p1_eval_frases_propias.csv'))
    args = ap.parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        filas = list(csv.DictReader(f))

    ok = {m: {c: 0 for c in CAMPOS} for m in ('laya', 'pc')}
    completas = {'laya': 0, 'pc': 0}
    tiempos, salida = [], []

    print(f'{len(filas)} frases de {args.csv}\n')
    print(f'{"esperado":8} {"p_v4":>5} {"p_v5":>5}  fallos de LAYA                              frase')
    print('-' * 110)
    for fila in filas:
        meta = esperado(fila)
        resp, ms = consultar(args.url, fila['frase'])
        tiempos.append(ms)
        ans = resp.get('answers', {})
        laya = decision_desde_laya(resp)
        pc = clasificar_palabras_clave(fila['frase'])
        p_v4 = float((ans.get('v4_noul') or {}).get('noul', 1.0))
        p_v5 = max(float((ans.get(q) or {}).get('noul', 1.0)) for q in EXTRA if q.startswith('v5_'))

        for metodo, d in (('laya', laya), ('pc', pc)):
            malos = [c for c in CAMPOS if d[c] != meta[c]]
            for c in CAMPOS:
                ok[metodo][c] += c not in malos
            completas[metodo] += not malos
        fallos = ', '.join(f'{c}={laya[c]}' for c in CAMPOS if laya[c] != meta[c] and c != 'permitido')
        print(f'{"segura" if meta["permitido"] else "PROHIB.":8} {p_v4:5.2f} {p_v5:5.2f}  '
              f'{fallos[:42]:42}  {fila["frase"]}')

        salida.append({'frase': fila['frase'],
                       **{f'esperado_{c}': meta[c] for c in CAMPOS},
                       **{f'laya_{c}': laya[c] for c in CAMPOS},
                       **{f'pc_{c}': pc[c] for c in CAMPOS},
                       'laya_p_peligro_v4': round(p_v4, 4), 'laya_p_peligro_v5': round(p_v5, 4),
                       'latencia_total_ms': round(ms, 1)})

    os.makedirs(os.path.dirname(os.path.abspath(args.salida)), exist_ok=True)
    with open(args.salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(salida[0]))
        w.writeheader()
        w.writerows(salida)

    n = len(filas)
    print('-' * 110)
    print(f'\nEXACTITUD POR CAMPO ({n} frases)        LAYA      palabras clave')
    for c in CAMPOS:
        nota = '   (LAYA = pregunta A/B actual)' if c == 'permitido' else ''
        print(f'  {c:10} {100 * ok["laya"][c] / n:20.0f} % {100 * ok["pc"][c] / n:12.0f} %{nota}')
    print(f'  {"COMPLETA":10} {100 * completas["laya"] / n:20.0f} % {100 * completas["pc"] / n:12.0f} %')
    print(f'\nLatencia por petición: mediana {statistics.median(tiempos):.0f} ms, máximo {max(tiempos):.0f} ms')
    print(f'CSV guardado en {args.salida}')


if __name__ == '__main__':
    main()
