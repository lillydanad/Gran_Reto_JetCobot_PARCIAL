"""transcriptor_voz — Pregunta 3 del parcial (Grupo 4).

Toma el audio (micrófono o archivo), lo transcribe en español con Google AI Studio
(Gemini) y entrega el texto a la cadena: broker -> /interpretar_orden -> cola -> brazo.

- La clave se lee de la variable de entorno GEMINI_API_KEY (o GOOGLE_API_KEY).
  Nunca está en el código ni en el repositorio.
- Tiene su propio tiempo límite (tiempo_limite_s). Si la transcripción no llega a
  tiempo, no hay clave o no hay internet: MODO TEXTO por teclado, y lo informa.
- Guarda cada audio (.wav) junto a su transcripción (.txt) en evidencias/p3_audios/,
  y una fila por orden en evidencias/p3_voz.csv con los tiempos de cada etapa.

    ros2 run parcial_g4 transcriptor_voz --ros-args -p client_id:=cielo
    ros2 run parcial_g4 transcriptor_voz --ros-args -p archivo_audio:=/ruta/orden.wav
"""

import base64
import csv
import datetime
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TiempoAgotado

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from arm_broker_interfaces.action import MoveArm

URL_GEMINI = 'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent'
INSTRUCCION = ('Transcribe exactamente lo que dice este audio, en español. Es una orden hablada para '
               'un brazo robótico. Devuelve SOLO el texto dicho, sin comillas ni explicaciones. '
               'Si no se entiende nada, devuelve una cadena vacía.')
MIME = {'.wav': 'audio/wav', '.mp3': 'audio/mp3', '.ogg': 'audio/ogg', '.flac': 'audio/flac',
        '.aac': 'audio/aac', '.m4a': 'audio/aac'}
CAMPOS = ['fecha', 'client_id', 'audio', 'modo', 'causa_modo_texto', 'transcripcion', 'lo_que_se_dijo',
          'aceptada', 'motivo_rechazo', 'accion', 'objeto', 'color', 'prioridad', 'degradada',
          'resultado_brazo', 'captura_s', 'transcripcion_s', 'decision_s', 'espera_cola_s',
          'percepcion_s', 'ik_s', 'plan_s', 'voz_a_movimiento_s', 'correcta']


class TranscriptorVoz(Node):

    def __init__(self):
        super().__init__('transcriptor_voz')
        self.declare_parameter('client_id', 'voz')
        self.declare_parameter('dispositivo', 'plughw:0,0')   # micrófono de la cámara USB del Jetson
        self.declare_parameter('archivo_audio', '')
        self.declare_parameter('modelo', 'gemini-flash-latest')
        self.declare_parameter('tiempo_limite_s', 8.0)
        self.declare_parameter('max_grabacion_s', 15)
        self.declare_parameter('carpeta', '~/parcial_ws_G4/evidencias')
        self.client_id = self.get_parameter('client_id').value
        self.carpeta = os.path.expanduser(self.get_parameter('carpeta').value)
        os.makedirs(os.path.join(self.carpeta, 'p3_audios'), exist_ok=True)
        self.cli = ActionClient(self, MoveArm, 'move_arm')
        self.create_subscription(String, '/arm/rechazos', self._rechazo, 10)
        self.rechazos = {}
        self.hilos = ThreadPoolExecutor(max_workers=2)

    def p(self, nombre):
        return self.get_parameter(nombre).value

    # ---------------------------------------------------------------- audio
    def grabar(self, ruta):
        """Graba hasta que la persona presiona Enter. Devuelve (hora_fin_de_habla, captura_s)."""
        proc = subprocess.Popen(['arecord', '-q', '-D', self.p('dispositivo'), '-f', 'S16_LE',
                                 '-r', '16000', '-c', '1', '-d', str(int(self.p('max_grabacion_s'))), ruta],
                                stderr=subprocess.PIPE)
        input('   🎙  GRABANDO... habla y presiona Enter apenas TERMINES de hablar ')
        t_fin_habla = time.time()
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)                  # arecord cierra bien el .wav
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        if not os.path.exists(ruta) or os.path.getsize(ruta) < 1000:
            error = proc.stderr.read().decode(errors='ignore').strip() if proc.stderr else ''
            raise RuntimeError(f'no se grabó audio ({error or "¿micrófono correcto?"})')
        return t_fin_habla, time.time() - t_fin_habla

    def _llamar_gemini(self, ruta):
        clave = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        if not clave:
            raise RuntimeError('no hay GEMINI_API_KEY en el entorno de esta terminal')
        with open(ruta, 'rb') as f:
            audio = base64.b64encode(f.read()).decode()
        cuerpo = {'contents': [{'parts': [
            {'text': INSTRUCCION},
            {'inline_data': {'mime_type': MIME.get(os.path.splitext(ruta)[1].lower(), 'audio/wav'),
                             'data': audio}}]}],
            'generationConfig': {'temperature': 0}}
        req = urllib.request.Request(URL_GEMINI.format(modelo=self.p('modelo')),
                                     data=json.dumps(cuerpo).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'x-goog-api-key': clave})
        with urllib.request.urlopen(req, timeout=float(self.p('tiempo_limite_s')) + 2) as r:
            resp = json.loads(r.read())
        partes = resp['candidates'][0]['content'].get('parts', [])
        return ' '.join(pt.get('text', '') for pt in partes).strip().strip('"')

    def transcribir(self, ruta):
        """Devuelve (texto, segundos, causa). causa != '' significa que hay que ir a modo texto."""
        limite = float(self.p('tiempo_limite_s'))
        t0 = time.time()
        try:
            texto = self.hilos.submit(self._llamar_gemini, ruta).result(timeout=limite)
            if not texto:
                return '', time.time() - t0, 'la transcripción vino vacía'
            return texto, time.time() - t0, ''
        except TiempoAgotado:
            return '', time.time() - t0, f'la transcripción no llegó en {limite:.1f} s'
        except urllib.error.HTTPError as e:
            return '', time.time() - t0, f'Google AI Studio respondió HTTP {e.code}'
        except Exception as e:                               # noqa: BLE001 — sin internet, DNS, etc.
            return '', time.time() - t0, f'sin transcripción ({type(e).__name__}: {str(e)[:80]})'

    # ---------------------------------------------------------------- broker
    def _rechazo(self, msg):
        try:
            r = json.loads(msg.data)
        except ValueError:
            return
        if r.get('client_id') == self.client_id:
            self.rechazos[r.get('frase')] = r

    def enviar(self, frase):
        goal = MoveArm.Goal()
        goal.frase = frase
        goal.client_id = self.client_id
        listo = threading.Event()
        caja = {}
        fut = self.cli.send_goal_async(goal)
        fut.add_done_callback(lambda f: (caja.update(handle=f.result()), listo.set()))
        if not listo.wait(timeout=15):
            return {'aceptada': False, 'motivo': 'el broker no respondió'}
        handle = caja['handle']
        if not handle.accepted:
            fin = time.time() + 3
            while frase not in self.rechazos and time.time() < fin:
                time.sleep(0.05)
            r = self.rechazos.pop(frase, {})
            return {'aceptada': False, 'motivo': r.get('motivo', '(sin motivo)'),
                    'decision': r.get('decision', {})}
        print('   ✓ en la cola del broker; esperando al brazo...', flush=True)
        listo.clear()
        handle.get_result_async().add_done_callback(lambda f: (caja.update(res=f.result()), listo.set()))
        listo.wait(timeout=600)
        r = caja['res'].result
        return {'aceptada': True, 'exito': r.success, 'mensaje': r.message,
                'decision': {'accion': r.accion, 'objeto': r.objeto, 'color': r.color,
                             'prioridad': r.prioridad_modelo, 'degradada': r.degradada},
                'tiempos': json.loads(r.tiempos_json or '{}')}

    # ---------------------------------------------------------------- registro
    def registrar(self, fila):
        ruta = os.path.join(self.carpeta, 'p3_voz.csv')
        nuevo = not os.path.exists(ruta)
        with open(ruta, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction='ignore')
            if nuevo:
                w.writeheader()
            w.writerow({k: fila.get(k, '') for k in CAMPOS})

    def una_orden(self, comando):
        marca = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        wav = os.path.join(self.carpeta, 'p3_audios', f'{marca}.wav')
        fila = {'fecha': datetime.datetime.now().isoformat(timespec='seconds'), 'client_id': self.client_id}
        captura = transcripcion_s = 0.0
        causa = ''
        if comando == 't':
            modo, t_fin_habla = 'teclado (elegido)', None
            texto = input('   Escribe la orden: ').strip()
        else:
            archivo = self.p('archivo_audio')
            if archivo:
                shutil.copy(os.path.expanduser(archivo), wav)
                t_fin_habla = time.time()
            else:
                t_fin_habla, captura = self.grabar(wav)
            texto, transcripcion_s, causa = self.transcribir(wav)
            modo = 'voz'
            if causa:
                print(f'   ⚠ MODO TEXTO: {causa}. El brazo no queda esperando.', flush=True)
                texto = input('   Escribe la orden: ').strip()
                modo = 'teclado (respaldo)'
            with open(wav[:-4] + '.txt', 'w', encoding='utf-8') as f:
                f.write(f'transcripcion: {texto if modo == "voz" else ""}\nmodo: {modo}\n'
                        f'causa_modo_texto: {causa}\ntexto_enviado: {texto}\n')
            fila['audio'] = os.path.relpath(wav, self.carpeta)
        if not texto:
            print('   (orden vacía, no se envía)')
            return
        print(f'   Texto enviado: "{texto}"', flush=True)
        r = self.enviar(texto)
        d, t = r.get('decision', {}), r.get('tiempos', {})
        voz_a_mov = (t['t_inicio_movimiento'] - t_fin_habla
                     if t_fin_habla and t.get('t_inicio_movimiento') else None)
        fila.update(modo=modo, causa_modo_texto=causa, transcripcion=texto if modo == 'voz' else '',
                    aceptada=r['aceptada'], motivo_rechazo=r.get('motivo', ''),
                    accion=d.get('accion', ''), objeto=d.get('objeto', ''), color=d.get('color', ''),
                    prioridad=d.get('prioridad', ''), degradada=d.get('degradada', ''),
                    resultado_brazo=r.get('mensaje', 'rechazada: ' + r.get('motivo', '')),
                    captura_s=round(captura, 3), transcripcion_s=round(transcripcion_s, 3),
                    voz_a_movimiento_s=round(voz_a_mov, 2) if voz_a_mov else '')
        for k in ('decision_s', 'espera_cola_s', 'percepcion_s', 'ik_s', 'plan_s'):
            if t.get(k) is not None:
                fila[k] = round(float(t[k]), 3)
        self.registrar(fila)
        if r['aceptada']:
            print(f'   ✓ {"HECHO" if r.get("exito") else "FALLÓ"}: {r.get("mensaje")}')
            if voz_a_mov:
                print(f'   ⏱ de la voz al movimiento: {voz_a_mov:.1f} s  (captura {captura:.2f} · '
                      f'transcripción {transcripcion_s:.2f} · decisión {t.get("decision_s", 0):.2f} · '
                      f'cola {t.get("espera_cola_s", 0):.2f} · percepción {t.get("percepcion_s", 0):.2f} · '
                      f'IK {t.get("ik_s", 0):.2f} · plan {t.get("plan_s", 0):.2f})')
        else:
            print(f'   ✗ RECHAZADA: {r.get("motivo")}')


def main(args=None):
    rclpy.init(args=args)
    nodo = TranscriptorVoz()
    ejecutor = MultiThreadedExecutor(num_threads=4)
    ejecutor.add_node(nodo)
    hilo = threading.Thread(target=ejecutor.spin, daemon=True)
    hilo.start()
    try:
        print(f'[{nodo.client_id}] esperando al broker...', flush=True)
        if not nodo.cli.wait_for_server(timeout_sec=15.0):
            print('El broker no aparece. ¿Está corriendo y esta terminal hizo source ~/g4.sh?')
            return
        clave = 'sí' if (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')) else 'NO'
        print(f'Listo · modelo {nodo.p("modelo")} · tiempo límite {nodo.p("tiempo_limite_s")} s · '
              f'clave en el entorno: {clave}')
        while True:
            c = input('\n[Enter] grabar una orden · [t] escribirla · [q] salir > ').strip().lower()
            if c == 'q':
                break
            try:
                nodo.una_orden(c)
            except RuntimeError as e:
                print(f'   ⚠ {e}')
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        ejecutor.shutdown()
        hilo.join(timeout=2.0)
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
