#!/usr/bin/env python3
"""Tabla de intentos de la Pregunta 2 (Grupo 4).

    python3 herramientas/tabla_p2.py --marcar   # pregunta, intento por intento, si salió bien
    python3 herramientas/tabla_p2.py            # solo imprime la tabla y la tasa de éxito

Lee evidencias/p2_intentos.csv (lo escribe el worker) y genera evidencias/p2_tabla.md.
'exito_visual' lo decide una persona mirando el brazo: ¿el objeto correcto quedó en la
zona correcta? El worker no puede saberlo solo.
"""
import argparse
import csv
import os
import statistics

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CSV = os.path.join(RAIZ, 'evidencias', 'p2_intentos.csv')
SALIDA = os.path.join(RAIZ, 'evidencias', 'p2_tabla.md')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--marcar', action='store_true')
    ap.add_argument('--csv', default=CSV)
    args = ap.parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        lector = csv.DictReader(f)
        campos, filas = lector.fieldnames, list(lector)

    if args.marcar:
        for i, f in enumerate(filas, 1):
            if f.get('exito_visual', '').strip():
                continue
            r = input(f'\n#{i} [{f["client_id"]}] "{f["frase"]}" -> {f["resultado"]} ({f["detalle"]})\n'
                      '   ¿El objeto correcto quedó en la zona correcta? [s/n, Enter = saltar] ').strip().lower()
            if r in ('s', 'n'):
                f['exito_visual'] = 'si' if r == 's' else 'no'
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            w.writerows(filas)

    lineas = ['| # | Cliente | Frase | Color | Posición | Resultado del worker | Éxito (visual) | Error FK (mm) | Vía |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    errores, exitos, marcados = [], 0, 0
    for i, f in enumerate(filas, 1):
        err = float(f['error_mm']) if f.get('error_mm') not in ('', None) else -1
        if err >= 0:
            errores.append(err)
        if f.get('exito_visual') in ('si', 'no'):
            marcados += 1
            exitos += f['exito_visual'] == 'si'
        lineas.append(f'| {i} | {f["client_id"]} | {f["frase"]} | {f["color"]} | {f.get("posicion", "")} | '
                      f'{f["resultado"]}: {f["detalle"]} | {f.get("exito_visual") or "?"} | '
                      f'{err:.1f} | {f.get("via", "")} |' if err >= 0 else
                      f'| {i} | {f["client_id"]} | {f["frase"]} | {f["color"]} | {f.get("posicion", "")} | '
                      f'{f["resultado"]}: {f["detalle"]} | {f.get("exito_visual") or "?"} | — | {f.get("via", "")} |')

    resumen = [f'\nIntentos: {len(filas)} · marcados a la vista: {marcados}']
    if marcados:
        resumen.append(f'Tasa de éxito: {exitos}/{marcados} = {100 * exitos / marcados:.0f} %')
    if errores:
        resumen.append(f'Error FK (mm): mediana {statistics.median(errores):.1f} · '
                       f'media {statistics.mean(errores):.1f} · máximo {max(errores):.1f} (n={len(errores)})')
    texto = '\n'.join(lineas + resumen)
    print(texto)
    salida = os.path.join(os.path.dirname(os.path.abspath(args.csv)), 'p2_tabla.md')
    with open(salida, 'w', encoding='utf-8') as f:
        f.write(texto + '\n')
    print(f'\nTabla guardada en {salida}')


if __name__ == '__main__':
    main()
