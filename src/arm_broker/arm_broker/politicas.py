"""Políticas de cola — ítems 2 y 3."""

import threading
import time


class Pedido:
    def __init__(self, goal_handle, client_id, priority, joint_positions):
        self.goal_handle = goal_handle
        self.goal_id = bytes(goal_handle.goal_id.uuid).hex()[:12]
        self.client_id = client_id
        self.priority = int(priority)
        self.joint_positions = list(joint_positions)
        self.t_llegada = time.time()
        self.t_inicio_ejec = None
        self.fin = threading.Event()
        self.resultado = None

    @property
    def espera_s(self):
        fin = self.t_inicio_ejec if self.t_inicio_ejec else time.time()
        return fin - self.t_llegada

    def __repr__(self):
        return f'<{self.client_id} p{self.priority} {self.goal_id}>'


class Politica:
    nombre = 'base'

    def siguiente(self, pendientes):
        raise NotImplementedError

    def atendido(self, pedido):
        pass


# ============================== IMPLEMENTAR · ítems 2 y 3 =========================
class FIFO(Politica):
    """Atiende las solicitudes estrictamente en el orden cronológico de llegada."""
    nombre = 'fifo'

    def siguiente(self, pendientes):
        if len(pendientes) == 0:
            return None
        # Busca y devuelve el índice del elemento con el tiempo de llegada más antiguo
        return min(range(len(pendientes)), key=lambda idx: pendientes[idx].t_llegada)


class SegundaPolitica(Politica):
    """Sistema de prioridad que incluye envejecimiento para evitar bloqueos permanentes."""
    nombre = 'prioridad'

    def __init__(self, tau_s=8.0):
        self.factor_tiempo = float(tau_s)

    def obtener_puntaje(self, solicitud):
        if self.factor_tiempo <= 0:
            return float(solicitud.priority)
        return solicitud.priority + (solicitud.espera_s / self.factor_tiempo)

    def siguiente(self, pendientes):
        if len(pendientes) == 0:
            return None
        # Ordena primero por el mejor puntaje calculado; en caso de empate, por antigüedad
        return max(range(len(pendientes)),
                   key=lambda idx: (self.obtener_puntaje(pendientes[idx]), -pendientes[idx].t_llegada))
# =================================================================================


POLITICAS = {
    'fifo': FIFO,
    'prioridad': SegundaPolitica,
}
