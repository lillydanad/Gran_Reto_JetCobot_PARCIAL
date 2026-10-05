"""cliente_orden — cada integrante levanta el suyo (Pregunta 2 y 3).

Envía órdenes en lenguaje natural al broker (acción move_arm). El cliente NO pone
prioridad: la decide el modelo dentro del broker. Si el broker rechaza la orden,
el motivo llega por /arm/rechazos y se imprime aquí.

    ros2 run parcial_g4 cliente_orden --ros-args -p client_id:=cielo
        -> modo interactivo: escribe una orden por línea (Enter vacío o 'salir' termina)
    ros2 run parcial_g4 cliente_orden --ros-args -p client_id:=hugo -p frase:="trae el bloque rojo"
    ros2 run parcial_g4 cliente_orden --ros-args -p client_id:=dani -p archivo:=datos/rafaga.txt -p pausa_s:=0.2
"""

import json
import threading
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from arm_broker_interfaces.action import MoveArm


class ClienteOrden(Node):

    def __init__(self):
        super().__init__('cliente_orden')
        self.declare_parameter('client_id', 'alumno')
        self.declare_parameter('frase', '')
        self.declare_parameter('archivo', '')
        self.declare_parameter('pausa_s', 0.5)
        self.client_id = self.get_parameter('client_id').value
        self.cli = ActionClient(self, MoveArm, 'move_arm')
        self.create_subscription(String, '/arm/rechazos', self._rechazo, 10)
        self.pendientes = 0
        self.lock = threading.Lock()

    def _rechazo(self, msg):
        try:
            r = json.loads(msg.data)
        except ValueError:
            return
        if r.get('client_id') == self.client_id:
            print(f'  ✗ RECHAZADA "{r.get("frase")}": {r.get("motivo")}', flush=True)

    def enviar(self, frase):
        goal = MoveArm.Goal()
        goal.frase = frase
        goal.client_id = self.client_id
        t0 = time.time()
        with self.lock:
            self.pendientes += 1
        fut = self.cli.send_goal_async(goal, feedback_callback=self._feedback)
        fut.add_done_callback(lambda f: self._respuesta(f, frase, t0))

    def _feedback(self, msg):
        f = msg.feedback
        if f.state == 'QUEUED':
            return
        self.get_logger().info(f'{f.state} t={f.elapsed_s:.1f}s', throttle_duration_sec=2.0)

    def _respuesta(self, fut, frase, t0):
        handle = fut.result()
        if not handle.accepted:
            print(f'  ✗ el broker no aceptó "{frase}" (motivo arriba)', flush=True)
            self._terminar_una()
            return
        print(f'  ✓ EN COLA "{frase}"', flush=True)
        handle.get_result_async().add_done_callback(lambda r: self._resultado(r, frase, t0))

    def _resultado(self, fut, frase, t0):
        r = fut.result().result
        marca = '✓' if r.success else '✗'
        print(f'  {marca} TERMINADA "{frase}": {r.accion} {r.objeto} {r.color} '
              f'prioridad {r.prioridad_modelo}{" (degradada)" if r.degradada else ""} | '
              f'espera {r.wait_time_s:.1f}s ejec {r.exec_time_s:.1f}s total {time.time() - t0:.1f}s'
              + (f' | error {r.error_mm:.1f} mm' if r.error_mm >= 0 else '')
              + f' | {r.message}', flush=True)
        self._terminar_una()

    def _terminar_una(self):
        with self.lock:
            self.pendientes -= 1

    def esperar_todo(self, tope_s=600.0):
        fin = time.time() + tope_s
        while time.time() < fin:
            with self.lock:
                if self.pendientes <= 0:
                    return
            time.sleep(0.1)


def main(args=None):
    rclpy.init(args=args)
    nodo = ClienteOrden()
    ejecutor = MultiThreadedExecutor(num_threads=4)
    ejecutor.add_node(nodo)
    threading.Thread(target=ejecutor.spin, daemon=True).start()

    print(f'[{nodo.client_id}] esperando al broker...', flush=True)
    if not nodo.cli.wait_for_server(timeout_sec=15.0):
        print('El broker no aparece. ¿Está corriendo y esta terminal hizo source ~/g4.sh?')
        rclpy.shutdown()
        return

    frase = nodo.get_parameter('frase').value.strip()
    archivo = nodo.get_parameter('archivo').value.strip()
    pausa = float(nodo.get_parameter('pausa_s').value)
    try:
        if frase:
            nodo.enviar(frase)
            nodo.esperar_todo()
        elif archivo:
            with open(archivo, encoding='utf-8') as f:
                frases = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            for fr in frases:
                nodo.enviar(fr)
                time.sleep(pausa)
            nodo.esperar_todo()
        else:
            print(f'[{nodo.client_id}] escribe una orden y Enter (Enter vacío o "salir" termina)')
            while True:
                linea = input('> ').strip()
                if not linea or linea.lower() == 'salir':
                    break
                nodo.enviar(linea)
            print('esperando las órdenes que siguen en curso...')
            nodo.esperar_todo()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
