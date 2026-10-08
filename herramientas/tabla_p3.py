#!/usr/bin/env python3
"""Entregables de la Pregunta 3 (Grupo 4) a partir de evidencias/p3_voz.csv.

    python3 herramientas/tabla_p3.py --marcar --ultimas 5   # completa lo dicho y si fue correcta
    python3 herramientas/tabla_p3.py --ultimas 5            # solo tablas y figura

Genera:
  evidencias/p3_tabla.md     tabla de las órdenes (Parte B) + desglose de tiempos (Parte C)
  evidencias/p3_desglose.png figura: barras apiladas por etapa, por orden y en promedio
"""
import argparse
import csv
import os
import statistics

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CSV = os.path.join(RAIZ, 'evidencias', 'p3_voz.csv')
ETAPAS = [('captura_s', 'Captura del audio'), ('transcripcion_s', 'Transcripción (nube)'),
          ('decision_s', 'Decisión del modelo'), ('espera_cola_s', 'Espera en la cola'),
          ('percepcion_s', 'Percepción'), ('ik_s', 'Cinemática inversa'),
          ('plan_s', 'Planificación')]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--marcar', action='store_true')
    ap.add_argument('--ultimas', type=int, default=0, help='usar solo las últimas N órdenes')
    ap.add_argument('--csv', default=CSV)
    args = ap.parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        lector = csv.DictReader(f)
        campos, todas = lector.fieldnames, list(lector)
    filas = todas[-args.ultimas:] if args.ultimas else todas

    if args.marcar:
        for f in filas:
            print(f'\n[{f["fecha"]}] transcrito/escrito: "{f["transcripcion"] or "(modo texto)"}" -> '
                  f'{"RECHAZADA: " + f["motivo_rechazo"] if f["aceptada"] != "True" else f["resultado_brazo"]}')
            if not f.get('lo_que_se_dijo'):
                f['lo_que_se_dijo'] = input('   ¿Qué se DIJO exactamente? ').strip()
            if not f.get('correcta'):
                r = input('   ¿El resultado final fue el esperado (incluido rechazar si correspondía)? [s/n] ')
                f['correcta'] = 'si' if r.strip().lower() == 's' else 'no'
        with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=campos)
            w.writeheader()
            w.writerows(todas)

    # ---- Parte B
    md = ['## Parte B — Órdenes habladas', '',
          '| # | Lo que se dijo | Lo que transcribió el sistema | Decisión del modelo | Lo que hizo el brazo | ¿Correcta? |',
          '| --- | --- | --- | --- | --- | --- |']
    for i, f in enumerate(filas, 1):
        transc = f['transcripcion'] or f'(modo texto: {f["causa_modo_texto"] or "elegido"})'
        decision = (f'{f["accion"]} · {f["objeto"]} · {f["color"]} · prioridad {f["prioridad"]}'
                    + (' (degradada)' if f.get('degradada') == 'True' else ''))
        brazo = f['resultado_brazo'] if f['aceptada'] == 'True' else f'nada: rechazada ({f["motivo_rechazo"]})'
        md.append(f'| {i} | {f.get("lo_que_se_dijo") or "?"} | {transc} | {decision} | {brazo} | '
                  f'{f.get("correcta") or "?"} |')
    correctas = sum(f.get('correcta') == 'si' for f in filas)
    md += ['', f'Correctas: {correctas}/{len(filas)}', '']

    # ---- Parte C
    # Solo órdenes por VOZ: en modo texto el tiempo de tipeo inflaría 'Otros'
    medidas = [f for f in filas if num(f.get('voz_a_movimiento_s')) and f.get('modo') == 'voz']
    md += ['## Parte C — De la voz al movimiento (segundos)', '',
           '| # | ' + ' | '.join(n for _, n in ETAPAS) + ' | Otros* | Total medido |',
           '| --- ' * (len(ETAPAS) + 3) + '|']
    series = {k: [] for k, _ in ETAPAS}
    series['otros'], totales = [], []
    for i, f in enumerate(medidas, 1):
        valores = [num(f.get(k)) or 0.0 for k, _ in ETAPAS]
        total = num(f['voz_a_movimiento_s'])
        otros = max(0.0, total - sum(valores))
        for (k, _), v in zip(ETAPAS, valores):
            series[k].append(v)
        series['otros'].append(otros)
        totales.append(total)
        md.append(f'| {i} | ' + ' | '.join(f'{v:.2f}' for v in valores) + f' | {otros:.2f} | {total:.2f} |')
    if medidas:
        medias = {k: statistics.mean(v) for k, v in series.items()}
        md.append('| Promedio | ' + ' | '.join(f'{medias[k]:.2f}' for k, _ in ETAPAS)
                  + f' | {medias["otros"]:.2f} | {statistics.mean(totales):.2f} |')
        dominante = max((k for k, _ in ETAPAS), key=lambda k: medias[k])
        nombre = dict(ETAPAS)[dominante]
        md += ['', '*Otros: transporte ROS, envío del goal y respuesta del broker (total medido − suma de etapas).',
               '', f'Etapa dominante: **{nombre}**, {medias[dominante]:.2f} s de '
               f'{statistics.mean(totales):.2f} s ({100 * medias[dominante] / statistics.mean(totales):.0f} %).']
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            etiquetas = [f'Orden {i}' for i in range(1, len(medidas) + 1)] + ['Promedio']
            fig, ax = plt.subplots(figsize=(9, 0.6 * len(etiquetas) + 1.8))
            izquierda = [0.0] * len(etiquetas)
            for k, n in ETAPAS + [('otros', 'Otros')]:
                vals = series[k] + [medias[k]]
                ax.barh(etiquetas, vals, left=izquierda, label=n)
                izquierda = [a + b for a, b in zip(izquierda, vals)]
            ax.invert_yaxis()
            ax.set_xlabel('segundos desde que el operador termina de hablar')
            ax.set_title('De la voz al movimiento: tiempo por etapa')
            ax.legend(loc='lower right', fontsize=8)
            fig.tight_layout()
            figura = os.path.join(os.path.dirname(os.path.abspath(args.csv)), 'p3_desglose.png')
            fig.savefig(figura, dpi=150)
            md += ['', f'Figura: {os.path.basename(figura)}']
            print(f'Figura guardada en {figura}')
        except ImportError:
            print('Falta matplotlib para la figura: pip3 install matplotlib')
    texto = '\n'.join(md)
    print('\n' + texto)
    salida = os.path.join(os.path.dirname(os.path.abspath(args.csv)), 'p3_tabla.md')
    with open(salida, 'w', encoding='utf-8') as f:
        f.write(texto + '\n')
    print(f'\nTablas guardadas en {salida}')


if __name__ == '__main__':
    main()
