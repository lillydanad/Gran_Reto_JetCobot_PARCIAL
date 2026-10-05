#!/usr/bin/env python3
"""Medición de la Pregunta 1 a través del servicio /interpretar_orden.

    python3 herramientas/medir_p1.py --etiqueta calma
    python3 herramientas/medir_p1.py --etiqueta carga --paralelo 8
    python3 herramientas/medir_p1.py --csv datos/frases_profe.csv --etiqueta calma

Mide como un cliente real: llama al SERVICIO (no a LAYA directamente), así que
respeta la regla de que solo interprete_ordenes habla con la PC Windows.

- --paralelo N: N frases a la vez (simula a varios clientes consultando juntos).
- Si el CSV trae las columnas esperadas (accion, objeto, color, prioridad,
  permitido), calcula la exactitud de LAYA, de las palabras clave y del sistema.
- Guarda evidencias/p1_<etiqueta>.csv: una fila por frase con la decisión de cada
  método y todos los tiempos. Es el CSV entregable de la P1.

Requiere: source ~/g4.sh y el nodo interprete_ordenes corriendo.
"""
import argparse
import csv
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from arm_broker_interfaces.srv import InterpretarOrden

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CAMPOS = ['accion', 'objeto', 'color', 'prioridad', 'permitido']


def p95(xs):
    if not xs:
        return float('nan')
    o = sorted(xs)
    return o[max(0, min(len(o) - 1, int(round(0.95 * (len(o) - 1)))))]


def resumen(nombre, xs):
    xs = [x for x in xs if x is not None and x >= 0]
    if not xs:
        return f'  {nombre:28} sin datos'
    return (f'  {nombre:28} mediana {statistics.median(xs):8.1f} ms   p95 {p95(xs):8.1f} ms'
            f'   (n={len(xs)})')


def esperado(fila):
    if not all(c in fila and fila[c].strip() for c in CAMPOS):
        return None
    return {'accion': fila['accion'].strip(), 'objeto': fila['objeto'].strip(),
            'color': fila['color'].strip(), 'prioridad': int(fila['prioridad']),
            'permitido': fila['permitido'].strip() in ('1', 'true', 'True', 'si')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=os.path.join(RAIZ, 'datos', 'frases_propias.csv'))
    ap.add_argument('--etiqueta', default='calma')
    ap.add_argument('--paralelo', type=int, default=1)
    ap.add_argument('--client_id', default='medidor')
    args = ap.parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        filas = list(csv.DictReader(f))

    rclpy.init()
    nodo = Node('medidor_p1')
    cli = nodo.create_client(InterpretarOrden, '/interpretar_orden')
    ejecutor = MultiThreadedExecutor(num_threads=4)
    ejecutor.add_node(nodo)
    threading.Thread(target=ejecutor.spin, daemon=True).start()
    if not cli.wait_for_service(timeout_sec=10.0):
        print('No encuentro /interpretar_orden. ¿Está corriendo el nodo y hiciste source ~/g4.sh?')
        return

    def llamar(fila):
        req = InterpretarOrden.Request()
        req.frase = fila['frase']
        req.client_id = args.client_id
        listo = threading.Event()
        t0 = time.perf_counter()
        fut = cli.call_async(req)
        fut.add_done_callback(lambda _: listo.set())
        listo.wait(timeout=30.0)
        return fila, fut.result(), (time.perf_counter() - t0) * 1000.0

    print(f'{len(filas)} frases de {args.csv} | {args.paralelo} en paralelo | etiqueta "{args.etiqueta}"')
    t_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
        resultados = list(pool.map(llamar, filas))
    t_lote = time.perf_counter() - t_inicio

    filas_csv, servicio, total, laya, red, servidor = [], [], [], [], [], []
    ok = {m: {c: 0 for c in CAMPOS} for m in ('laya', 'palabras_clave', 'sistema')}
    completas = {m: 0 for m in ok}
    n_laya, n_etiq, degradadas, estimado = 0, 0, 0, False

    for fila, r, ms in resultados:
        if r is None:
            print(f'  SIN RESPUESTA: {fila["frase"]}')
            continue
        det = json.loads(r.detalle or '{}')
        sistema = {'accion': r.accion, 'objeto': r.objeto, 'color': r.color,
                   'prioridad': r.prioridad, 'permitido': r.permitido}
        metodos = {'laya': det.get('laya'), 'palabras_clave': det.get('palabras_clave'),
                   'sistema': sistema}
        degradadas += r.degradada
        estimado = estimado or r.tiempo_servidor_estimado
        servicio.append(ms)
        total.append(r.tiempo_total_ms)
        laya.append(r.tiempo_laya_ms)
        red.append(r.tiempo_red_ms)
        servidor.append(r.tiempo_servidor_ms)

        meta = esperado(fila)
        if meta:
            n_etiq += 1
            n_laya += metodos['laya'] is not None
            for m, d in metodos.items():
                if d is None:
                    continue
                malos = [c for c in CAMPOS if d[c] != meta[c]]
                for c in CAMPOS:
                    ok[m][c] += c not in malos
                completas[m] += not malos

        fila_csv = {'frase': fila['frase']}
        if meta:
            fila_csv.update({f'esperado_{c}': meta[c] for c in CAMPOS})
        for m, d in metodos.items():
            fila_csv.update({f'{m}_{c}': (d[c] if d else '') for c in CAMPOS})
        fila_csv.update({'motivo': r.motivo, 'degradada': r.degradada,
                         'tiempo_servicio_ms': round(ms, 1),
                         'tiempo_nodo_ms': round(r.tiempo_total_ms, 1),
                         'tiempo_laya_ms': round(r.tiempo_laya_ms, 1),
                         'tiempo_red_ms': round(r.tiempo_red_ms, 1),
                         'tiempo_servidor_ms': round(r.tiempo_servidor_ms, 1),
                         'servidor_estimado': r.tiempo_servidor_estimado})
        filas_csv.append(fila_csv)

    salida = os.path.join(RAIZ, 'evidencias', f'p1_{args.etiqueta}.csv')
    os.makedirs(os.path.dirname(salida), exist_ok=True)
    with open(salida, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(filas_csv[0]))
        w.writeheader()
        w.writerows(filas_csv)

    n = len(filas_csv)
    print(f'\nLATENCIA ({args.etiqueta}, {args.paralelo} en paralelo, lote completo en {t_lote:.1f} s)')
    print(resumen('servicio (lo que ve el cliente)', servicio))
    print(resumen('dentro del nodo', total))
    print(resumen('LAYA ida y vuelta (red+cálculo)', laya))
    print(resumen('red (/health)', red))
    print(resumen('servidor' + (' (estimado = LAYA - red)' if estimado else ' (informado)'), servidor))
    print(f'  degradadas: {degradadas}/{n} = {100 * degradadas / max(1, n):.0f} %')

    if n_etiq:
        print(f'\nEXACTITUD ({n_etiq} frases etiquetadas; LAYA respondió en {n_laya})')
        print(f'  {"campo":10} {"LAYA":>8} {"pal. clave":>11} {"SISTEMA":>9}')
        for c in CAMPOS + ['COMPLETA']:
            fila = []
            for m, base in (('laya', n_laya), ('palabras_clave', n_etiq), ('sistema', n_etiq)):
                v = completas[m] if c == 'COMPLETA' else ok[m][c]
                fila.append(f'{100 * v / base:7.0f}%' if base else '      -')
            print(f'  {c:10} {fila[0]:>8} {fila[1]:>11} {fila[2]:>9}')
        print('  SISTEMA = la decisión final que devuelve el servicio (LAYA + veto de seguridad)')
    print(f'\nCSV: {salida}')

    nodo.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
