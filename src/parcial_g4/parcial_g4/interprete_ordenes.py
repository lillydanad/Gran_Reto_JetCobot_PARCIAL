"""Nodo interprete_ordenes — Pregunta 1 del parcial (Grupo 4).

Expone el servicio /interpretar_orden: recibe una frase en español y devuelve una
decisión tipada (accion, objeto, color, prioridad, permitido).

- Consulta al servidor LAYA por HTTP. Es el ÚNICO nodo que habla con la PC Windows.
- Si LAYA no responde dentro de 'tiempo_limite_s', resuelve con el clasificador por
  palabras clave y marca la respuesta como degradada. Nunca se queda esperando.

    ros2 run parcial_g4 interprete_ordenes
    ros2 run parcial_g4 interprete_ordenes --ros-args -p url_laya:=http://IP:PUERTO/v1/systemone -p tiempo_limite_s:=1.0
"""

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TiempoAgotado

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from arm_broker_interfaces.srv import InterpretarOrden
from parcial_g4.decision import (clasificar_palabras_clave, decision_desde_laya,
                                 fusionar, motivo_rechazo, preguntas_laya)

# Si el servidor informa su propio tiempo de cálculo con alguno de estos nombres, se usa.
CLAVES_TIEMPO_SERVIDOR = ('inference_time_ms', 'latency_ms', 'elapsed_ms',
                          'server_time_ms', 'compute_ms')


class InterpreteOrdenes(Node):

    def __init__(self):
        super().__init__('interprete_ordenes')
        self.declare_parameter('url_laya', 'http://172.51.9.2:5000/v1/systemone')
        self.declare_parameter('tiempo_limite_s', 1.0)
        self.declare_parameter('modelo', 'multilingual')
        self.declare_parameter('preset', '')     # lo entrega el docente; vacío = no se envía

        # Hilos para las consultas HTTP: permiten cortar la espera a tiempo exacto.
        self.hilos_http = ThreadPoolExecutor(max_workers=32)
        # Reentrant: atiende varias frases a la vez (4 clientes + broker en paralelo).
        self.create_service(InterpretarOrden, '/interpretar_orden', self.atender,
                            callback_group=ReentrantCallbackGroup())
        self.get_logger().info(
            f'interprete_ordenes listo · LAYA={self.p("url_laya")} · '
            f'tiempo límite={self.p("tiempo_limite_s")} s')

    def p(self, nombre):
        # Se lee en cada petición: se puede cambiar en vivo con `ros2 param set`.
        return self.get_parameter(nombre).value

    def _consultar_laya(self, frase, limite):
        cuerpo = {'state': {'body': frase}, 'model': self.p('modelo'),
                  'questions': preguntas_laya()}
        if self.p('preset'):
            cuerpo['preset'] = self.p('preset')
        req = urllib.request.Request(self.p('url_laya'), data=json.dumps(cuerpo).encode(),
                                     headers={'Content-Type': 'application/json'})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=limite + 1.0) as r:
            resp = json.loads(r.read())
        return resp, (time.perf_counter() - t0) * 1000.0

    def _medir_red(self, limite):
        """Ida y vuelta a /health: no usa el modelo, así que es (casi) solo red."""
        u = urllib.parse.urlsplit(self.p('url_laya'))
        t0 = time.perf_counter()
        with urllib.request.urlopen(f'{u.scheme}://{u.netloc}/health', timeout=limite + 1.0) as r:
            r.read()
        return (time.perf_counter() - t0) * 1000.0

    def atender(self, peticion, respuesta):
        t0 = time.perf_counter()
        frase = peticion.frase.strip()
        limite = float(self.p('tiempo_limite_s'))
        pc = clasificar_palabras_clave(frase)      # instantáneo: siempre listo como respaldo

        tiempo_laya, tiempo_servidor, tiempo_red, estimado = -1.0, -1.0, -1.0, False
        causa, laya_cruda = '', None
        # La medición de red va EN PARALELO a la consulta: no agrega espera.
        fut_red = self.hilos_http.submit(self._medir_red, limite)
        try:
            resp, tiempo_laya = self.hilos_http.submit(
                self._consultar_laya, frase, limite).result(timeout=limite)
            laya_cruda = decision_desde_laya(resp)
            decision = fusionar(laya_cruda, pc)
            for clave in CLAVES_TIEMPO_SERVIDOR:
                if clave in resp:
                    tiempo_servidor = float(resp[clave])
        except TiempoAgotado:
            causa = f'LAYA no respondió en {limite:.2f} s'
        except Exception as e:                      # red caída, JSON inválido, HTTP 4xx/5xx...
            causa = f'LAYA falló ({type(e).__name__})'

        try:
            restante = limite - (time.perf_counter() - t0)   # nunca pasarse del límite
            tiempo_red = fut_red.result(timeout=0.01 if causa else max(0.01, restante))
        except Exception:
            tiempo_red = -1.0
        if tiempo_servidor < 0 and tiempo_laya >= 0 and tiempo_red >= 0:
            tiempo_servidor = max(0.0, tiempo_laya - tiempo_red)
            estimado = True

        degradada = bool(causa)
        if degradada:
            decision = pc
            self.get_logger().warn(f'DEGRADADA [{peticion.client_id}] {causa}')

        respuesta.accion = decision['accion']
        respuesta.objeto = decision['objeto']
        respuesta.color = decision['color']
        respuesta.prioridad = int(decision['prioridad'])
        respuesta.permitido = bool(decision['permitido'])
        respuesta.motivo = motivo_rechazo(decision)
        respuesta.degradada = degradada
        respuesta.metodo = 'palabras_clave' if degradada else 'laya'
        respuesta.tiempo_laya_ms = tiempo_laya
        respuesta.tiempo_servidor_ms = tiempo_servidor
        respuesta.tiempo_red_ms = tiempo_red
        respuesta.tiempo_servidor_estimado = estimado
        respuesta.detalle = json.dumps({'laya': laya_cruda, 'palabras_clave': pc,
                                        'causa_degradada': causa}, ensure_ascii=False)
        respuesta.tiempo_total_ms = (time.perf_counter() - t0) * 1000.0

        self.get_logger().info(
            f'[{peticion.client_id or "?"}] "{frase}" -> {respuesta.accion}/{respuesta.objeto}/'
            f'{respuesta.color} p{respuesta.prioridad} permitido={respuesta.permitido} '
            f'{respuesta.metodo} {respuesta.tiempo_total_ms:.0f} ms'
            + (f' | {respuesta.motivo}' if respuesta.motivo else ''))
        return respuesta

    def destroy_node(self):
        self.hilos_http.shutdown(wait=False)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    nodo = InterpreteOrdenes()
    ejecutor = MultiThreadedExecutor(num_threads=16)   # hasta 16 frases a la vez
    ejecutor.add_node(nodo)
    try:
        ejecutor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
