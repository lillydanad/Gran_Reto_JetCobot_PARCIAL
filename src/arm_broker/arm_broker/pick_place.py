"""Pick and place real del worker — Pregunta 2 del parcial (Grupo 4).

Lo usa SOLO el worker del broker (execute_callback), cuando simular:=false. Este
módulo es el único dueño de /dev/ttyUSB0 durante la demostración.

Cadena por cada orden 'recoger <color>':
  1. PERCEPCIÓN : va a la pose de observación, toma una foto y ubica el bloque.
  2. IK         : MoveIt /compute_ik da los ángulos para el agarre y para 6 cm encima.
  3. PLAN       : MoveIt /plan_kinematic_path planifica cada tramo (MoveIt NO ejecuta).
  4. EJECUCIÓN  : el worker envía los puntos de la trayectoria al brazo (send_angles).
  5. AGARRE, TRASLADO por 'seleccion', DEPÓSITO y vuelta a HOME.
  6. ERROR      : |FK_RB2(ángulos pedidos) - FK_RB2(ángulos leídos)| en el agarre.
Cada intento queda en evidencias/p2_intentos.csv con su foto en evidencias/p2_fotos/.
"""

import csv
import datetime
import json
import math
import os
import subprocess
import time

from builtin_interfaces.msg import Duration
from geometry_msgs.msg import PoseStamped
from moveit_msgs.msg import Constraints, JointConstraint, RobotState
from moveit_msgs.srv import GetMotionPlan, GetPositionFK, GetPositionIK
from rclpy.callback_groups import ReentrantCallbackGroup
from sensor_msgs.msg import JointState

from arm_broker import fk

GRUPO, PUNTA = 'arm_group', '6_Link'
MARCOS = ('world', 'base_link', 'dummy')
VELOCIDAD_MAXIMA = 50              # regla del curso
SUBIDAS_M = (0.06, 0.04, 0.025)    # pre-agarre: se prueba 6 cm sobre el bloque, luego 4 y 2,5
TOLERANCIA_LLEGADA_DEG = 3.0
TRAMOS_ESTRICTOS = ('sobre el bloque', 'agarre')   # sin llegar aquí, NO se cierra la pinza
FRACCION_PREAGARRE = 0.3   # pre-agarre articular: 30 % del camino de vuelta a la observación
DRIVERS_PROHIBIDOS = ('sync_plan', 'mycobot_receiver', 'control_sync_plan')
CAMPOS_CSV = ['fecha', 'client_id', 'frase', 'color', 'posicion', 'pixel', 'via',
              'q_pedido_deg', 'q_real_deg', 'pos_pedida_mm', 'pos_alcanzada_mm', 'error_mm',
              'espera_cola_s', 'percepcion_s', 'ik_s', 'plan_s', 'ejecucion_s', 'total_s',
              'resultado', 'detalle', 'exito_visual']


class FalloOrden(Exception):
    pass


class Cancelada(Exception):
    pass


def _deg(q):
    return [round(math.degrees(a), 2) for a in q]


def _rad(q):
    return [math.radians(a) for a in q]


class PickPlace:

    def __init__(self, nodo, archivo_puntos, puerto, velocidad, registro, zona_deposito):
        self.n = nodo
        self.log = nodo.get_logger()
        self.vel = max(5, min(int(velocidad), VELOCIDAD_MAXIMA))
        self.registro = os.path.expanduser(registro)
        self.zona = zona_deposito.strip()
        with open(os.path.expanduser(archivo_puntos), encoding='utf-8') as f:
            datos = json.load(f)
        self.puntos = {k: _rad(v['angulos']) for k, v in datos.get('puntos', {}).items()}
        self.posiciones = datos.get('posiciones', {})
        faltan = [p for p in ('home', 'observacion', 'seleccion') if p not in self.puntos]
        if faltan or not self.posiciones:
            raise RuntimeError(f'{archivo_puntos} incompleto: faltan {faltan or "posiciones de agarre"}')

        ocupado = subprocess.run(['fuser', puerto], capture_output=True, text=True).stdout.strip()
        if ocupado:
            raise RuntimeError(f'{puerto} está ocupado por el PID {ocupado}. Corre ~/apagar_todo.sh '
                               '(y sudo systemctl stop yahboom_app.service si avisa).')
        from pymycobot.mycobot import MyCobot
        self.mc = MyCobot(puerto, 1000000)
        time.sleep(0.5)
        self.mc.power_on()
        time.sleep(0.5)
        try:
            self.mc.set_fresh_mode(1)        # cada comando nuevo reemplaza al anterior (como sync_plan_nx)
        except Exception:                    # noqa: BLE001
            pass

        g = ReentrantCallbackGroup()
        self.cli_fk = nodo.create_client(GetPositionFK, '/compute_fk', callback_group=g)
        self.cli_ik = nodo.create_client(GetPositionIK, '/compute_ik', callback_group=g)
        self.cli_plan = nodo.create_client(GetMotionPlan, '/plan_kinematic_path', callback_group=g)
        self.marco = None
        self.log.info(f'PickPlace listo · {puerto} · velocidad {self.vel} · '
                      f'{len(self.posiciones)} posiciones · depósito '
                      f'{self.zona or "por color (deposito_<color>)"}')

    # ------------------------------------------------------------- utilidades
    def _llamar(self, cli, req, tope=5.0):
        if not cli.wait_for_service(timeout_sec=1.0):
            return None
        fut = cli.call_async(req)
        fin = time.time() + tope
        while not fut.done() and time.time() < fin:
            time.sleep(0.005)
        return fut.result() if fut.done() else None

    @staticmethod
    def _estado(q):
        rs = RobotState()
        rs.joint_state = JointState(name=list(fk.JOINT_NAMES), position=[float(a) for a in q])
        return rs

    def _verificar_exclusividad(self):
        """Ningún driver de Yahboom puede estar escuchando /joint_states: movería el brazo también."""
        for info in self.n.get_subscriptions_info_by_topic('/joint_states'):
            if any(p in info.node_name for p in DRIVERS_PROHIBIDOS):
                raise FalloOrden(f'el nodo {info.node_name} escucha /joint_states y también movería '
                                 'el brazo. Apágalo (~/apagar_todo.sh) antes de la demo.')

    def leer_angulos(self):
        for _ in range(10):
            v = self.mc.get_angles()
            if isinstance(v, list) and len(v) == 6:
                return _rad(v)
            time.sleep(0.1)
        raise FalloOrden('el brazo no responde a get_angles')

    def _publicar_real(self):
        q = self.leer_angulos()
        self.n.mover(q)                     # /joint_states sale SOLO del broker
        return q

    # ------------------------------------------------------------- MoveIt
    def _fk_pose(self, q):
        for marco in ([self.marco] if self.marco else MARCOS):
            req = GetPositionFK.Request()
            req.header.frame_id = marco
            req.fk_link_names = [PUNTA]
            req.robot_state = self._estado(q)
            r = self._llamar(self.cli_fk, req)
            if r is not None and r.error_code.val == 1 and r.pose_stamped:
                self.marco = marco
                return r.pose_stamped[0].pose
        return None

    def _ik(self, pose, semilla):
        req = GetPositionIK.Request()
        req.ik_request.group_name = GRUPO
        req.ik_request.robot_state = self._estado(semilla)
        req.ik_request.avoid_collisions = False
        req.ik_request.ik_link_name = PUNTA
        req.ik_request.pose_stamped = PoseStamped()
        req.ik_request.pose_stamped.header.frame_id = self.marco
        req.ik_request.pose_stamped.pose = pose
        req.ik_request.timeout = Duration(sec=0, nanosec=300_000_000)
        r = self._llamar(self.cli_ik, req)
        if r is None:
            return None, 'sin respuesta'
        if r.error_code.val != 1:
            return None, r.error_code.val
        mapa = dict(zip(r.solution.joint_state.name, r.solution.joint_state.position))
        return [mapa[j] for j in fk.JOINT_NAMES], 1

    def _plan(self, desde, hasta):
        req = GetMotionPlan.Request()
        m = req.motion_plan_request
        m.group_name = GRUPO
        m.start_state = self._estado(desde)
        m.goal_constraints = [Constraints(joint_constraints=[
            JointConstraint(joint_name=j, position=float(a), tolerance_above=0.01,
                            tolerance_below=0.01, weight=1.0)
            for j, a in zip(fk.JOINT_NAMES, hasta)])]
        m.num_planning_attempts = 3
        m.allowed_planning_time = 2.0
        m.max_velocity_scaling_factor = 0.3
        m.max_acceleration_scaling_factor = 0.3
        r = self._llamar(self.cli_plan, req, tope=6.0)
        if r is None or r.motion_plan_response.error_code.val != 1:
            return None
        jt = r.motion_plan_response.trajectory.joint_trajectory
        orden = [jt.joint_names.index(j) for j in fk.JOINT_NAMES]
        return [(p.time_from_start.sec + p.time_from_start.nanosec / 1e9,
                 [p.positions[i] for i in orden]) for p in jt.points]

    # ------------------------------------------------------------- movimiento
    def ir(self, objetivo, etiqueta, gh, t):
        """Planifica con MoveIt y ejecuta. Sin MoveIt, va directo (queda anotado en 'via')."""
        self._revisar_cancelacion(gh)
        ok, razon = fk.dentro_de_limites(objetivo)
        if not ok:
            raise FalloOrden(f'{etiqueta}: {razon}')
        desde = self.leer_angulos()
        t0 = time.time()
        tramo = self._plan(desde, objetivo)
        t['plan_s'] += time.time() - t0
        if tramo is None:
            self.log.warn(f'{etiqueta}: MoveIt no planificó; voy directo con send_angles')
            t['via'] += f'+{etiqueta.replace(" ", "_")}_directo'
            tramo = [(0.0, desde), (2.0, objetivo)]
        else:
            recorte = max(abs(math.degrees(a - b)) for a, b in zip(tramo[-1][1], objetivo))
            if recorte > 1.0:
                # MoveIt deja la trayectoria en el límite de SU modelo (URDF), más estrecho que el
                # brazo real. Se usa su trayectoria hasta ahí y el último tramo va directo.
                self.log.warn(f'{etiqueta}: MoveIt recortó la trayectoria {recorte:.0f}° por los '
                              'límites de su modelo; el tramo final va directo')
                t['via'] += f'+{etiqueta.replace(" ", "_")}_final_directo'
                tramo = tramo + [(tramo[-1][0] + 1.5, list(objetivo))]
        t0 = time.time()
        ultimo_t, ultimo = -1.0, None
        for ts, q in tramo:                              # 1 punto cada ~0,5 s + el final
            if ts - ultimo_t < 0.5 and q is not tramo[-1][1]:
                continue
            self._revisar_cancelacion(gh)
            if not fk.dentro_de_limites(q)[0]:
                raise FalloOrden(f'{etiqueta}: la trayectoria sale de los límites articulares')
            self.mc.send_angles(_deg(q), self.vel)
            time.sleep(max(0.15, ts - ultimo_t if ultimo_t >= 0 else 0.15))
            self._publicar_real()
            ultimo_t, ultimo = ts, q
        q, llego, falta = self._esperar_llegada(objetivo, etiqueta)   # se compara con lo PEDIDO
        t['ejecucion_s'] += time.time() - t0
        if not llego:
            if etiqueta in TRAMOS_ESTRICTOS or etiqueta.startswith('deposito'):
                raise FalloOrden(f'{etiqueta}: el brazo no llegó (quedó a {falta:.0f}° del objetivo)')
            self.log.warn(f'{etiqueta}: quedó a {falta:.0f}° del objetivo; sigo')

    def _esperar_llegada(self, objetivo, etiqueta):
        """Espera a que el brazo llegue. El tope crece con lo que falta recorrer; si se
        detiene antes de llegar, reenvía el objetivo una vez. Devuelve (q, llegó, grados que faltan)."""
        def falta(q):
            return max(abs(math.degrees(a - b)) for a, b in zip(q, objetivo))
        q = self._publicar_real()
        fin = time.time() + 6.0 + 0.3 * falta(q)          # 120° por recorrer -> ~42 s de tope
        reenviado, ultimo_avance, previo = False, time.time(), q
        while time.time() < fin:
            if falta(q) < TOLERANCIA_LLEGADA_DEG:
                return q, True, falta(q)
            if max(abs(math.degrees(a - b)) for a, b in zip(q, previo)) > 0.3:
                ultimo_avance, previo = time.time(), q
            elif time.time() - ultimo_avance > 2.5:        # se quedó quieto sin llegar
                if reenviado:
                    break
                self.log.warn(f'{etiqueta}: se detuvo a {falta(q):.0f}°; reenvío el objetivo')
                self.mc.send_angles(_deg(objetivo), self.vel)
                reenviado, ultimo_avance = True, time.time()
            time.sleep(0.2)
            q = self._publicar_real()
        self.log.warn(f'{etiqueta}: no llegó a menos de {TOLERANCIA_LLEGADA_DEG}° (faltan {falta(q):.0f}°)')
        return q, False, falta(q)

    def pinza(self, abierta):
        self.mc.set_gripper_value(100 if abierta else 10, 30)
        time.sleep(1.5)

    @staticmethod
    def _revisar_cancelacion(gh):
        if gh.is_cancel_requested:
            raise Cancelada()

    # ------------------------------------------------------------- percepción
    def _ubicar(self, color, intento):
        import cv2
        from parcial_g4 import vision
        frame = vision.capturar()
        vistos = vision.detectar(frame)
        carpeta = os.path.join(os.path.dirname(self.registro), 'p2_fotos')
        os.makedirs(carpeta, exist_ok=True)
        cv2.imwrite(os.path.join(carpeta, f'{intento}_{color}.jpg'), vision.dibujar(frame, vistos))
        if color not in vistos:
            raise FalloOrden(f'la cámara no ve el bloque {color} sobre la mesa')
        px = vistos[color]['centro']
        con_pixel = {k: v for k, v in self.posiciones.items() if v.get('pixel')}
        if con_pixel:
            nombre = min(con_pixel, key=lambda k: math.dist(con_pixel[k]['pixel'], px))
        else:
            nombre = f'pos_{color}'
        if nombre not in self.posiciones:
            raise FalloOrden(f'no hay posición de agarre calibrada para {color}')
        return nombre, px

    # ------------------------------------------------------------- orden completa
    def ejecutar(self, gh, tarea):
        """Devuelve (estado, mensaje, error_mm) con estado en 'ok' | 'fallo' | 'cancelado'."""
        d = tarea.decision
        color = d['color']
        intento = datetime.datetime.now().strftime('%H%M%S')
        t = {'percepcion_s': 0.0, 'ik_s': 0.0, 'plan_s': 0.0, 'ejecucion_s': 0.0, 'via': 'moveit'}
        fila = {'fecha': datetime.datetime.now().isoformat(timespec='seconds'),
                'client_id': tarea.client_id, 'frase': getattr(tarea.goal_handle.request, 'frase', ''),
                'color': color, 'espera_cola_s': round(tarea.espera_s, 2), 'error_mm': -1}
        t_inicio = time.time()
        estado, mensaje, error_mm = 'fallo', '', -1.0
        try:
            self._verificar_exclusividad()
            if d['accion'] in ('volver_inicio', 'detener'):
                self._feedback(gh, 'HOME')
                self.ir(self.puntos['home'], 'home', gh, t)
                estado, mensaje = 'ok', 'brazo en HOME'
                return estado, mensaje, error_mm

            deposito = self.zona or f'deposito_{color}'      # se revisa ANTES de mover nada
            if deposito not in self.puntos:
                raise FalloOrden(f'no hay punto "{deposito}" calibrado: corre ensenar_puntos.py '
                                 f'--puntos {deposito} o usa -p zona_deposito:=<punto>')

            # 1. PERCEPCIÓN
            self._feedback(gh, 'PERCEPCION')
            t0 = time.time()
            self.pinza(True)
            self.ir(self.puntos['observacion'], 'observacion', gh, t)
            nombre, px = self._ubicar(color, intento)
            t['percepcion_s'] = time.time() - t0
            fila.update(posicion=nombre, pixel=px)

            # 2. IK con MoveIt hacia la pose de agarre y 6 cm encima
            self._feedback(gh, 'IK')
            t0 = time.time()
            q_ensenado = _rad(self.posiciones[nombre]['angulos'])
            pose_agarre = self._fk_pose(q_ensenado)
            if pose_agarre is None:
                raise FalloOrden('MoveIt no respondió a /compute_fk (¿está corriendo move_group?)')
            q_agarre, cod = self._ik(pose_agarre, q_ensenado)
            if q_agarre is None:
                self.log.warn(f'IK del agarre falló (código {cod}); uso los ángulos enseñados')
                q_agarre, t['via'] = q_ensenado, t['via'] + '+agarre_ensenado'
            q_arriba = None
            for subida in SUBIDAS_M:
                pose_arriba = type(pose_agarre)()
                pose_arriba.position.x = pose_agarre.position.x
                pose_arriba.position.y = pose_agarre.position.y
                pose_arriba.position.z = pose_agarre.position.z + subida
                pose_arriba.orientation = pose_agarre.orientation
                for semilla in (q_agarre, self.puntos['observacion'], self.puntos['home']):
                    q, cod = self._ik(pose_arriba, semilla)
                    if q is not None and fk.dentro_de_limites(q)[0]:
                        q_arriba = q
                        break
                if q_arriba is not None:
                    if subida != SUBIDAS_M[0]:
                        t['via'] += f'+preagarre_{subida * 100:.1f}cm'
                    break
            if q_arriba is None:
                obs = self.puntos['observacion']
                q_arriba = [g + FRACCION_PREAGARRE * (o - g) for g, o in zip(q_agarre, obs)]
                self.log.warn(f'sin IK para el pre-agarre (último código {cod}); uso un '
                              f'pre-agarre articular ({FRACCION_PREAGARRE:.0%} hacia la observación)')
                t['via'] += '+preagarre_articular'
            t['ik_s'] = time.time() - t0

            # 3-5. Plan + ejecución de cada tramo
            self._feedback(gh, 'AGARRE')
            self.ir(q_arriba, 'sobre el bloque', gh, t)
            self.ir(q_agarre, 'agarre', gh, t)
            q_real = self.leer_angulos()
            p_pedida, p_real = fk.fk(q_agarre), fk.fk(q_real)
            error_mm = math.dist(p_pedida, p_real)
            fila.update(q_pedido_deg=_deg(q_agarre), q_real_deg=_deg(q_real),
                        pos_pedida_mm=[round(v, 1) for v in p_pedida],
                        pos_alcanzada_mm=[round(v, 1) for v in p_real], error_mm=round(error_mm, 2))
            self.pinza(False)
            self.ir(q_arriba, 'subida', gh, t)

            self._feedback(gh, 'TRASLADO')
            self.ir(self.puntos['seleccion'], 'seleccion', gh, t)
            self.ir(self.puntos[deposito], deposito, gh, t)
            self.pinza(True)
            self.ir(self.puntos['seleccion'], 'seleccion', gh, t)
            self._feedback(gh, 'HOME')
            self.ir(self.puntos['home'], 'home', gh, t)
            estado = 'ok'
            mensaje = f'{color} desde {nombre} a {deposito} · error {error_mm:.1f} mm'
        except Cancelada:
            estado, mensaje = 'cancelado', 'cancelado por el cliente'
            self._a_salvo()
        except FalloOrden as e:
            mensaje = str(e)
            self.log.error(f'ORDEN FALLIDA: {mensaje}')
            self._a_salvo()
        except Exception as e:                            # noqa: BLE001 — nunca dejar el brazo a medias
            mensaje = f'error inesperado: {type(e).__name__}: {e}'
            self.log.error(mensaje)
            self._a_salvo()
        finally:
            t['total_s'] = time.time() - t_inicio
            fila.update({k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items()})
            fila.update(resultado=estado, detalle=mensaje, exito_visual='')
            self._registrar(fila)
        return estado, mensaje, error_mm

    def _a_salvo(self):
        """Ante un fallo: suelta lo que tenga y vuelve a HOME directo, despacio."""
        try:
            self.pinza(True)
            self.mc.send_angles(_deg(self.puntos['home']), min(self.vel, 25))
            self._esperar_llegada(self.puntos['home'], 'home de seguridad')
        except Exception as e:                            # noqa: BLE001
            self.log.error(f'no pude volver a HOME: {e}')

    def _feedback(self, gh, estado):
        from arm_broker_interfaces.action import MoveArm
        fb = MoveArm.Feedback()
        fb.state = estado
        gh.publish_feedback(fb)
        self.log.info(f'  -> {estado}')

    def _registrar(self, fila):
        nuevo = not os.path.exists(self.registro)
        os.makedirs(os.path.dirname(self.registro), exist_ok=True)
        with open(self.registro, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS_CSV, extrasaction='ignore')
            if nuevo:
                w.writeheader()
            w.writerow({k: fila.get(k, '') for k in CAMPOS_CSV})
