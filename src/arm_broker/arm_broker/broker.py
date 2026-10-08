"""arm_broker — el único nodo que publica en /joint_states.

Andamiaje entregado por el curso. Los bloques IMPLEMENTAR son lo que evalúa el
reto; el resto es instrumentación y se usa tal cual.

PARCIAL (Grupo 4): un goal puede traer una 'frase' en vez de ángulos. En ese caso
goal_callback consulta /interpretar_orden (Pregunta 1) ANTES de encolar: si la
decisión trae motivo de rechazo, el goal se rechaza con la causa (publicada en
/arm/rechazos); si no, se encola con la prioridad que decidió el modelo.
"""

import json
import threading
import time
import math #lo que nos va a permitir transformarlo a grados

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String

from arm_broker_interfaces.action import MoveArm
from arm_broker_interfaces.msg import QueueState
from arm_broker_interfaces.srv import InterpretarOrden
from parcial_g4.decision import clasificar_palabras_clave, motivo_rechazo

from arm_broker import fk
from arm_broker.politicas import POLITICAS, Pedido


class ArmBroker(Node):

    def __init__(self):
        super().__init__('arm_broker')

        self.declare_parameter('politica', 'fifo')
        self.declare_parameter('tau_envejecimiento_s', 8.0)
        self.declare_parameter('cola_max', 20)
        self.declare_parameter('paso_max_rad', 1.2)
        self.declare_parameter('duracion_movimiento_s', 3.0)
        self.declare_parameter('pasos_interpolacion', 10)
        # Parcial
        self.declare_parameter('tiempo_interprete_s', 2.5)  # tope para esperar a /interpretar_orden
        self.declare_parameter('simular', True)             # True = no mueve el brazo (Paso 7)
        self.declare_parameter('puntos_archivo', '~/parcial_ws_G4/datos/puntos_g4.json')
        self.declare_parameter('registro_intentos', '~/parcial_ws_G4/evidencias/p2_intentos.csv')
        self.declare_parameter('puerto', '/dev/ttyUSB0')
        self.declare_parameter('velocidad', 30)             # se recorta a 50 como máximo
        self.declare_parameter('zona_deposito', '')         # '' = deposito_<color>; o un punto fijo

        nombre = self.get_parameter('politica').value
        if nombre not in POLITICAS:
            raise RuntimeError(f'política desconocida: {nombre}. Hay {list(POLITICAS)}')
        clase = POLITICAS[nombre]
        if nombre == 'prioridad':
            self.politica = clase(self.get_parameter('tau_envejecimiento_s').value)
        else:
            self.politica = clase()

        self.cola_max = int(self.get_parameter('cola_max').value)
        self.paso_max = float(self.get_parameter('paso_max_rad').value)
        self.duracion = float(self.get_parameter('duracion_movimiento_s').value)
        self.pasos = max(1, int(self.get_parameter('pasos_interpolacion').value))

        self.grupo_entrada = ReentrantCallbackGroup()
        self.grupo_worker = MutuallyExclusiveCallbackGroup()

        self.lock = threading.Lock()
        self.pendientes = []
        self.por_goal_id = {}
        self.ejecutando = None
        self.q_actual = [0.0] * 6
        self.n_aceptados = 0
        self.n_rechazados = 0
        self.n_completados = 0
        self._parar = threading.Event()

        self.pub_joint = self.create_publisher(JointState, '/joint_states', 10)
        self.pub_cola = self.create_publisher(QueueState, '/arm/queue_state', 10)
        self.pub_rechazos = self.create_publisher(String, '/arm/rechazos', 10)
        self.cli_interprete = self.create_client(InterpretarOrden, '/interpretar_orden',
                                                 callback_group=self.grupo_entrada)
        self.decisiones = {}    # id(goal_request) -> decisión, de goal_callback a handle_accepted

        # PARCIAL: modo real. El worker abre el brazo y es su único dueño.
        self.pp = None
        if not self.get_parameter('simular').value:
            from arm_broker.pick_place import PickPlace
            self.pp = PickPlace(self,
                                self.get_parameter('puntos_archivo').value,
                                self.get_parameter('puerto').value,
                                self.get_parameter('velocidad').value,
                                self.get_parameter('registro_intentos').value,
                                self.get_parameter('zona_deposito').value)

        self.servidor = ActionServer(
            self,
            MoveArm,
            'move_arm',
            goal_callback=self.goal_callback,
            handle_accepted_callback=self.handle_accepted_callback,
            cancel_callback=self.cancel_callback,
            execute_callback=self.execute_callback,
            callback_group=self.grupo_entrada,
        )

        self.create_timer(0.2, self.publicar_estado_cola,
                          callback_group=self.grupo_worker)

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

        self.get_logger().info(
            f'arm_broker listo · política={self.politica.nombre} · '
            f'cola_max={self.cola_max} · único publicador de /joint_states · '
            f'simular={self.get_parameter("simular").value}')

    # ============================ PARCIAL · Pregunta 2 ============================
    def _interpretar(self, frase, usuario):
        """Pide la decisión a /interpretar_orden. Si no llega a tiempo, decide el
        clasificador por palabras clave aquí mismo (degradada). Nunca bloquea más
        de 'tiempo_interprete_s'."""
        limite = float(self.get_parameter('tiempo_interprete_s').value)
        if self.cli_interprete.wait_for_service(timeout_sec=0.2):
            req = InterpretarOrden.Request()
            req.frase = frase
            req.client_id = usuario
            fut = self.cli_interprete.call_async(req)
            fin = time.time() + limite
            while not fut.done() and time.time() < fin:
                time.sleep(0.005)
            r = fut.result() if fut.done() else None
            if r is not None:
                return {'accion': r.accion, 'objeto': r.objeto, 'color': r.color,
                        'prioridad': int(r.prioridad), 'permitido': r.permitido,
                        'motivo': r.motivo, 'degradada': r.degradada, 'metodo': r.metodo}
            causa = f'/interpretar_orden no respondió en {limite:.1f} s'
        else:
            causa = '/interpretar_orden no está disponible'
        d = clasificar_palabras_clave(frase)
        d.update(motivo=motivo_rechazo(d), degradada=True, metodo='palabras_clave (broker)')
        self.get_logger().warn(f'[{usuario}] {causa}: decide el clasificador local')
        return d

    def _rechazar(self, usuario, frase, motivo, decision=None):
        with self.lock:
            self.n_rechazados += 1
        datos = {'t': time.time(), 'client_id': usuario, 'frase': frase, 'motivo': motivo}
        if decision:
            datos['decision'] = {k: v for k, v in decision.items() if not k.startswith('_')}
        self.pub_rechazos.publish(String(data=json.dumps(datos, ensure_ascii=False)))
        self.get_logger().warn(f'DENEGADO [{usuario}] "{frase}" -> {motivo}')
        return GoalResponse.REJECT

    def _goal_con_frase(self, goal_request, usuario):
        frase = goal_request.frase.strip()
        t0 = time.time()
        d = self._interpretar(frase, usuario)
        d['t_decision_s'] = time.time() - t0                  # P3: etapa "decisión del modelo"
        if d['motivo']:
            return self._rechazar(usuario, frase, d['motivo'], d)
        with self.lock:
            total_en_cola = len(self.pendientes)
        if total_en_cola >= self.cola_max:
            return self._rechazar(usuario, frase, f'cola saturada ({total_en_cola}/{self.cola_max})', d)
        with self.lock:
            self.n_aceptados += 1
            self.decisiones[id(goal_request)] = d
        self.get_logger().info(
            f'APROBADO [{usuario}] "{frase}" -> {d["accion"]} {d["objeto"]} {d["color"]} '
            f'prioridad {d["prioridad"]} ({d["metodo"]}{", degradada" if d["degradada"] else ""})')
        return GoalResponse.ACCEPT

    def _ejecutar_orden(self, goal_handle, tarea):
        """Ejecuta una orden ya interpretada. Paso 7: simulación (el brazo NO se mueve).
        Paso 8 reemplaza la rama real por el pick and place."""
        d = tarea.decision
        respuesta = MoveArm.Result()
        respuesta.accion, respuesta.objeto, respuesta.color = d['accion'], d['objeto'], d['color']
        respuesta.prioridad_modelo = int(d['prioridad'])
        respuesta.degradada = bool(d['degradada'])
        respuesta.error_mm = -1.0
        t0 = time.time()
        tiempos = {'decision_s': d.get('t_decision_s'), 'espera_cola_s': tarea.espera_s}
        if self.pp is not None:                              # modo real (Paso 8)
            estado, mensaje, error_mm, t_pp = self.pp.ejecutar(goal_handle, tarea)
            tiempos.update(t_pp)
            respuesta.tiempos_json = json.dumps(tiempos)
            if estado == 'ok':
                goal_handle.succeed()
            elif estado == 'cancelado':
                goal_handle.canceled()
            else:
                goal_handle.abort()
            respuesta.success = estado == 'ok'
            respuesta.message = mensaje
            respuesta.error_mm = float(error_mm)
            respuesta.wait_time_s = tarea.espera_s
            respuesta.exec_time_s = time.time() - t0
            self.get_logger().info(f'ORDEN {estado.upper()} para {tarea.client_id}: {mensaje}')
            return respuesta
        retraso = self.duracion / self.pasos
        for _ in range(self.pasos):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                respuesta.success = False
                respuesta.message = 'cancelado'
                return respuesta
            fb = MoveArm.Feedback()
            fb.state = f'SIMULANDO {d["accion"]} {d["color"]}'
            fb.elapsed_s = time.time() - t0
            goal_handle.publish_feedback(fb)
            time.sleep(retraso)
        goal_handle.succeed()
        respuesta.success = True
        tiempos['t_inicio_movimiento'] = t0
        respuesta.tiempos_json = json.dumps(tiempos)
        respuesta.message = 'simulado: el brazo no se movió'
        respuesta.wait_time_s = tarea.espera_s
        respuesta.exec_time_s = time.time() - t0
        self.get_logger().info(f'ORDEN FINALIZADA (simulada) para {tarea.client_id}: '
                               f'{d["accion"]} {d["color"]}')
        return respuesta
    # ==============================================================================

    # ========================= IMPLEMENTAR · ítem 2 ==========================
    def goal_callback(self, goal_request):
        usuario = goal_request.client_id or 'Desconocido'
        if goal_request.frase.strip():                       # PARCIAL: orden en lenguaje natural
            return self._goal_con_frase(goal_request, usuario)
        if self.pp is not None:                               # en modo real solo órdenes con frase
            return self._rechazar(usuario, '(goal articular del RB-2)',
                                  'en modo real solo se aceptan órdenes con frase')
        angulos_solicitados = list(goal_request.joint_positions)

        # 1. Chequeo de límites articulares
        es_valido, razon = fk.dentro_de_limites(angulos_solicitados)
        if es_valido == False:
            with self.lock:
                self.n_rechazados += 1
            self.get_logger().warn(f'DENEGADO [{usuario}] -> Límites: {razon}')
            return GoalResponse.REJECT

        # 2. Chequeo de espacio de trabajo (workspace)
        es_valido, razon = fk.dentro_del_workspace(angulos_solicitados)
        if es_valido == False:
            with self.lock:
                self.n_rechazados += 1
            self.get_logger().warn(f'DENEGADO [{usuario}] -> Espacio: {razon}')
            return GoalResponse.REJECT

        # 3. Chequeo de movimiento brusco (paso articular)
        with self.lock:
            posicion_actual = list(self.q_actual)
            total_en_cola = len(self.pendientes)
        
        diferencia_max = fk.paso_articular(posicion_actual, angulos_solicitados)
        if diferencia_max > self.paso_max:
            with self.lock:
                self.n_rechazados += 1
            self.get_logger().warn(f'DENEGADO [{usuario}] -> Salto muy largo: {diferencia_max:.2f} rad (Tope: {self.paso_max:.2f})')
            return GoalResponse.REJECT

        # 4. Chequeo de saturación de cola
        if total_en_cola >= self.cola_max:
            with self.lock:
                self.n_rechazados += 1
            self.get_logger().warn(f'DENEGADO [{usuario}] -> Cola saturada ({total_en_cola}/{self.cola_max})')
            return GoalResponse.REJECT

        # Solicitud aprobada
        with self.lock:
            self.n_aceptados += 1
        cx, cy, cz = fk.fk(angulos_solicitados)
        self.get_logger().info(f'APROBADO [{usuario}] destino: ({cx:.0f}, {cy:.0f}, {cz:.0f}) mm')
        return GoalResponse.ACCEPT

    def handle_accepted_callback(self, goal_handle):
        req = goal_handle.request
        with self.lock:
            decision = self.decisiones.pop(id(req), None)
        # PARCIAL: con frase, la prioridad es la que decidió el modelo, no la del cliente
        prioridad = decision['prioridad'] if decision else req.priority
        nuevo_pedido = Pedido(goal_handle, req.client_id, prioridad, req.joint_positions)
        nuevo_pedido.decision = decision

        with self.lock:
            self.pendientes.append(nuevo_pedido)
            self.por_goal_id[nuevo_pedido.goal_id] = nuevo_pedido
            lugar_en_fila = len(self.pendientes)
            
        self.get_logger().info(f'AGREGADO A COLA: {nuevo_pedido.client_id} (Turno {lugar_en_fila})')

    def _worker(self):
        while not self._parar.is_set():
            tarea_actual = None
            with self.lock:
                if self.ejecutando is None and len(self.pendientes) > 0:
                    indice_elegido = self.politica.siguiente(self.pendientes)
                    if indice_elegido is not None:
                        tarea_actual = self.pendientes.pop(indice_elegido)
                        if tarea_actual.goal_handle.is_cancel_requested:
                            self.por_goal_id.pop(tarea_actual.goal_id, None)
                            tarea_actual = None
                        else:
                            self.ejecutando = tarea_actual
                            tarea_actual.t_inicio_ejec = time.time()
            
            if tarea_actual is None:
                time.sleep(0.02)
                continue

            tarea_actual.goal_handle.execute()
            tarea_actual.fin.wait()

            with self.lock:
                self.ejecutando = None
                self.por_goal_id.pop(tarea_actual.goal_id, None)
                self.n_completados += 1
                
            self.politica.atendido(tarea_actual)

    def execute_callback(self, goal_handle):
        id_tarea = bytes(goal_handle.goal_id.uuid).hex()[:12]
        with self.lock:
            tarea = self.por_goal_id.get(id_tarea)
            
        respuesta = MoveArm.Result()

        if tarea is None:
            goal_handle.abort()
            respuesta.success = False
            return respuesta

        if getattr(tarea, 'decision', None):                # PARCIAL: orden interpretada
            try:
                return self._ejecutar_orden(goal_handle, tarea)
            finally:
                tarea.fin.set()

        try:
            target_q = tarea.joint_positions
            with self.lock:
                inicio_q = list(self.q_actual)
                
            tiempo_arranque = time.time()
            retraso_paso = self.duracion / self.pasos

            for etapa in range(1, self.pasos + 1):
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    respuesta.success = False
                    return respuesta

                proporcion = etapa / self.pasos
                q_intermedio = [a + (b - a) * proporcion for a, b in zip(inicio_q, target_q)]
                self.mover(q_intermedio)

                progreso = MoveArm.Feedback()
                progreso.state = 'MOVIMIENTO_EN_PROGRESO'
                progreso.elapsed_s = time.time() - tiempo_arranque
                goal_handle.publish_feedback(progreso)
                
                time.sleep(retraso_paso)

            goal_handle.succeed()
            respuesta.success = True
            respuesta.wait_time_s = tarea.espera_s
            respuesta.exec_time_s = time.time() - tiempo_arranque
            self.get_logger().info(f'MOVIMIENTO FINALIZADO para {tarea.client_id}')
            return respuesta
            
        finally:
            tarea.fin.set()
    # =========================================================================
    # =========================================================================

    def cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    # ----------------------------------------------------------- publicar
    def mover(self, q):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'base_link'
        msg.name = fk.JOINT_NAMES
        msg.position = [float(v) for v in q]
        self.pub_joint.publish(msg)
        with self.lock:
            self.q_actual = list(q)

    def publicar_estado_cola(self):
        msg = QueueState()
        msg.stamp = self.get_clock().now().to_msg()
        with self.lock:
            ej = self.ejecutando
            msg.executing_client = ej.client_id if ej else ''
            msg.executing_goal_id = ej.goal_id if ej else ''
            msg.executing_elapsed_s = (time.time() - ej.t_inicio_ejec) if ej and ej.t_inicio_ejec else 0.0
            msg.queue_length = len(self.pendientes)
            msg.queued_goal_ids = [p.goal_id for p in self.pendientes]
            msg.queued_clients = [p.client_id for p in self.pendientes]
            msg.queued_priorities = [min(255, max(0, p.priority)) for p in self.pendientes]
            msg.queued_wait_s = [p.espera_s for p in self.pendientes]
            msg.total_accepted = self.n_aceptados
            msg.total_rejected = self.n_rechazados
            msg.total_completed = self.n_completados
            cola = list(self.pendientes)
        self.pub_cola.publish(msg)

        for posicion, p in enumerate(cola, start=1):
            try:
                fb = MoveArm.Feedback()
                fb.state = 'QUEUED'
                fb.queue_position = posicion
                fb.elapsed_s = p.espera_s
                p.goal_handle.publish_feedback(fb)
            except Exception:
                pass

    def destroy_node(self):
        self._parar.set()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    nodo = ArmBroker()
    executor = MultiThreadedExecutor(num_threads=12)   # admite varias frases a la vez
    executor.add_node(nodo)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        nodo.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
