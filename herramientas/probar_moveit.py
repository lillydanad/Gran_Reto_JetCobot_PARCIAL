#!/usr/bin/env python3
"""Paso 6b: MoveIt2 como calculadora (FK, IK y plan). NO mueve el brazo.

    Terminal A:  ros2 launch jetcobot_moveit move_group.launch.py allow_trajectory_execution:=false
    Terminal B:  python3 herramientas/probar_moveit.py

1. FK: para las 3 poses medidas en el RB-2 (ítem 1), compara la posición que da
   MoveIt (modelo URDF) con la que midió el firmware y con nuestra FK por DH.
   Sirve para saber si el modelo de MoveIt y el firmware usan el mismo marco.
2. IK: pide a MoveIt los ángulos para llegar a la pose 1 y revisa si vuelve a ellos.
3. Plan: pide una trayectoria desde POSE_HOME hasta esa solución y la resume.
"""
import math
import os
import sys

import rclpy
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import PoseStamped
from moveit_msgs.msg import Constraints, JointConstraint, RobotState
from moveit_msgs.srv import GetMotionPlan, GetPositionFK, GetPositionIK
from rclpy.node import Node
from sensor_msgs.msg import JointState

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(RAIZ, 'src', 'arm_broker'))
from arm_broker import fk as fk_rb2   # noqa: E402

ARTICULACIONES = ['1_Joint', '2_Joint', '3_Joint', '4_Joint', '5_Joint', '6_Joint']
GRUPO, BASE, PUNTA, PINZA = 'arm_group', 'base_link', '6_Link', 'jiazhua_Link'
POSE_HOME_DEG = [0, 0, 0, 0, 0, -45]

# Documento técnico del RB-2, ítem 1: ángulos enviados (°) -> coordenadas del firmware
POSES = [
    ('pose1', [0, -7, -80, -23, -10, -20], [161.8, -70.0, 170.6, 155.91, -0.05, -66.65]),
    ('pose2', [45, 20, 0, 0, 90, 0], [-60.1, -80.4, 392.6, -90.43, -20.73, 45.25]),
    ('pose3', [20, 20, 0, 20, 40, -20], [-78.1, -61.6, 403.3, -47.72, -42.21, -52.79]),
]
CODIGOS = {1: 'SUCCESS', -1: 'FAILURE', -2: 'PLANNING_FAILED', -4: 'CONTROL_FAILED',
           -10: 'START_STATE_IN_COLLISION', -12: 'GOAL_IN_COLLISION', -31: 'NO_IK_SOLUTION'}


def rad(v):
    return [math.radians(a) for a in v]


def deg(v):
    return [math.degrees(a) for a in v]


def matriz(q):
    x, y, z, w = q.x, q.y, q.z, q.w
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def rpy_fijo(R):
    """R = Rz(c)·Ry(b)·Rx(a): roll, pitch, yaw clásico."""
    return deg([math.atan2(R[2][1], R[2][2]), math.asin(max(-1, min(1, -R[2][0]))),
                math.atan2(R[1][0], R[0][0])])


def xyz_intrinseco(R):
    """R = Rx(a)·Ry(b)·Rz(c)."""
    return deg([math.atan2(-R[1][2], R[2][2]), math.asin(max(-1, min(1, R[0][2]))),
                math.atan2(-R[0][1], R[0][0])])


def estado(q_rad):
    rs = RobotState()
    rs.joint_state = JointState(name=ARTICULACIONES, position=[float(a) for a in q_rad])
    rs.is_diff = False
    return rs


def fmt(v, n=1):
    return '[' + ', '.join(f'{a:8.{n}f}' for a in v) + ']'


class Probador(Node):
    def __init__(self):
        super().__init__('probar_moveit')
        self.fk = self.create_client(GetPositionFK, '/compute_fk')
        self.ik = self.create_client(GetPositionIK, '/compute_ik')
        self.plan = self.create_client(GetMotionPlan, '/plan_kinematic_path')

    def llamar(self, cli, req):
        if not cli.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(f'No aparece {cli.srv_name}. ¿Está corriendo move_group?')
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10.0)
        return fut.result()

    def fk_moveit(self, q_rad):
        req = GetPositionFK.Request()
        req.header.frame_id = BASE
        req.fk_link_names = [PUNTA, PINZA]
        req.robot_state = estado(q_rad)
        r = self.llamar(self.fk, req)
        return {n: p.pose for n, p in zip(r.fk_link_names, r.pose_stamped)}, r.error_code.val

    def ik_moveit(self, pose, semilla_rad):
        req = GetPositionIK.Request()
        req.ik_request.group_name = GRUPO
        req.ik_request.robot_state = estado(semilla_rad)
        req.ik_request.avoid_collisions = False
        req.ik_request.ik_link_name = PUNTA
        req.ik_request.pose_stamped = PoseStamped()
        req.ik_request.pose_stamped.header.frame_id = BASE
        req.ik_request.pose_stamped.pose = pose
        req.ik_request.timeout = Duration(sec=1)
        r = self.llamar(self.ik, req)
        js = r.solution.joint_state
        mapa = dict(zip(js.name, js.position))
        return [mapa.get(j, float('nan')) for j in ARTICULACIONES], r.error_code.val

    def plan_moveit(self, desde_rad, hasta_rad):
        req = GetMotionPlan.Request()
        m = req.motion_plan_request
        m.group_name = GRUPO
        m.start_state = estado(desde_rad)
        m.goal_constraints = [Constraints(joint_constraints=[
            JointConstraint(joint_name=j, position=float(a), tolerance_above=0.01,
                            tolerance_below=0.01, weight=1.0)
            for j, a in zip(ARTICULACIONES, hasta_rad)])]
        m.num_planning_attempts = 5
        m.allowed_planning_time = 2.0
        m.max_velocity_scaling_factor = 0.3
        m.max_acceleration_scaling_factor = 0.3
        r = self.llamar(self.plan, req).motion_plan_response
        return r.trajectory.joint_trajectory.points, r.error_code.val, r.planning_time


def main():
    rclpy.init()
    n = Probador()

    print('=' * 92)
    print('1. FK: MoveIt (URDF) vs firmware (medido en el RB-2) vs nuestra FK (DH)   [mm y °]')
    print('=' * 92)
    pose1_moveit = None
    for nombre, q_deg, firmware in POSES:
        q = rad(q_deg)
        poses, cod = n.fk_moveit(q)
        dh = fk_rb2.fk(q)
        print(f'\n{nombre}  q = {q_deg} °   (FK MoveIt: {CODIGOS.get(cod, cod)})')
        print(f'  firmware   pos {fmt(firmware[:3])}   rx,ry,rz {fmt(firmware[3:], 2)}')
        print(f'  DH (RB-2)  pos {fmt(dh)}   dist. al firmware '
              f'{math.dist(dh, firmware[:3]):6.1f} mm')
        for link in (PUNTA, PINZA):
            p = poses.get(link)
            if p is None:
                continue
            pos = [p.position.x * 1000, p.position.y * 1000, p.position.z * 1000]
            R = matriz(p.orientation)
            print(f'  {link:12} pos {fmt(pos)}   dist. al firmware {math.dist(pos, firmware[:3]):6.1f} mm')
            print(f'  {"":12} rpy fijo XYZ {fmt(rpy_fijo(R), 2)}   XYZ intrínseco {fmt(xyz_intrinseco(R), 2)}')
        if nombre == 'pose1':
            pose1_moveit = poses.get(PUNTA)

    print('\n' + '=' * 92)
    print('2. IK: ángulos que MoveIt propone para llegar a la pose 1 (semilla = ceros)')
    print('=' * 92)
    q_ik, cod = n.ik_moveit(pose1_moveit, [0.0] * 6)
    print(f'  resultado: {CODIGOS.get(cod, cod)}')
    print(f'  original  {fmt(POSES[0][1])} °')
    print(f'  MoveIt IK {fmt(deg(q_ik))} °')
    if cod == 1:
        print(f'  FK(DH) de la solución {fmt(fk_rb2.fk(q_ik))} mm '
              f'vs FK(DH) del original {fmt(fk_rb2.fk(rad(POSES[0][1])))} mm')

    print('\n' + '=' * 92)
    print('3. PLAN: de POSE_HOME a la solución de la IK (MoveIt NO ejecuta)')
    print('=' * 92)
    destino = q_ik if cod == 1 else rad(POSES[0][1])
    puntos, cod_p, t_plan = n.plan_moveit(rad(POSE_HOME_DEG), destino)
    print(f'  resultado: {CODIGOS.get(cod_p, cod_p)}   tiempo de planificación {t_plan * 1000:.0f} ms')
    if puntos:
        dur = puntos[-1].time_from_start.sec + puntos[-1].time_from_start.nanosec / 1e9
        saltos = [max(abs(b - a) for a, b in zip(p0.positions, p1.positions))
                  for p0, p1 in zip(puntos, puntos[1:])]
        print(f'  {len(puntos)} puntos, duración {dur:.2f} s, salto máximo entre puntos '
              f'{math.degrees(max(saltos)) if saltos else 0:.1f} °')
        print(f'  primer punto {fmt(deg(puntos[0].positions))} °')
        print(f'  último punto {fmt(deg(puntos[-1].positions))} °')

    n.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
