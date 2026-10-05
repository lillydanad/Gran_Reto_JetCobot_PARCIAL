"""Decisión tipada de una orden en español — Pregunta 1 del parcial (Grupo 4).

Este módulo NO usa ROS. Contiene tres piezas que usan los nodos:
  1. El vocabulario cerrado de la decisión (qué valores puede tomar cada campo).
  2. preguntas_laya(): las preguntas tipadas que se le envían a LAYA
     (solo choice y score: el modelo elige, nunca redacta texto).
  3. clasificar_palabras_clave(): el clasificador propio de respaldo, que se usa
     cuando LAYA no responde a tiempo (respuesta "degradada").

Toda decisión es un dict con los mismos campos:
  accion, objeto, color, prioridad (int 1..3), permitido (bool), motivo (str)
"""

import re
import unicodedata

# ----------------------------------------------------------------------------
# 1. Vocabulario cerrado
# ----------------------------------------------------------------------------
ACCIONES = ['recoger', 'volver_inicio', 'detener', 'ninguna']
OBJETOS = ['bloque', 'otro', 'ninguno']
COLORES = ['rojo', 'verde', 'azul', 'amarillo', 'otro', 'ninguno']
COLORES_EN_MESA = ['rojo', 'verde', 'azul', 'amarillo']
PRIORIDAD_BAJA, PRIORIDAD_NORMAL, PRIORIDAD_ALTA = 1, 2, 3


def normalizar(texto):
    """Minúsculas, sin tildes ni signos: 'Tráelo ¡YA!' -> 'traelo ya'."""
    t = unicodedata.normalize('NFD', str(texto).lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9 ]', ' ', t)
    return ' '.join(t.split())


# ----------------------------------------------------------------------------
# 2. Preguntas tipadas para LAYA
# ----------------------------------------------------------------------------
def preguntas_laya():
    """Preguntas que se envían a LAYA. Solo 'choice' y 'score': salida tipada.

    'seguridad' usa claves neutras A/B en vez de un 'noul' true/false, porque la
    documentación de LAYA advierte que las etiquetas booleanas pueden sesgar la
    respuesta del modelo.
    """
    return {
        'accion': {
            'type': 'choice',
            'instructions': '¿Qué acción le pide la orden al brazo robótico?',
            'criteria': {
                'recoger': 'tomar, agarrar, traer, llevar, mover o poner un objeto',
                'volver_inicio': 'regresar el brazo a su posición inicial o de reposo',
                'detener': 'parar, detener o cancelar el movimiento del brazo',
                'ninguna': 'no pide ninguna acción, o pide NO hacer algo',
            },
        },
        'objeto': {
            'type': 'choice',
            'instructions': '¿Qué objeto menciona la orden?',
            'criteria': {
                'bloque': 'un bloque, cubo, pieza o ficha de color',
                'otro': 'un objeto que no es un bloque: pelota, botella, tijera, vaso',
                'ninguno': 'no menciona ningún objeto',
            },
        },
        'color': {
            'type': 'choice',
            'instructions': '¿De qué color es el objeto que pide la orden?',
            'criteria': {
                'rojo': 'rojo',
                'verde': 'verde',
                'azul': 'azul',
                'amarillo': 'amarillo',
                'otro': 'un color distinto de rojo, verde, azul o amarillo',
                'ninguno': 'no menciona ningún color',
            },
        },
        'prioridad': {
            'type': 'score',
            'instructions': '¿Qué tan urgente es la orden?',
            'criteria': ['sin apuro, cuando se pueda', 'normal',
                         'urgente, inmediato, rápido'],
        },
        'seguridad': {
            'type': 'choice',
            'instructions': '¿Es segura esta orden para un brazo robótico en un '
                            'laboratorio con personas?',
            'criteria': {
                'A': 'segura: recoger, llevar o mover bloques sobre la mesa '
                     'con normalidad',
                'B': 'peligrosa o prohibida: lanzar, tirar, golpear, romper, '
                     'máxima velocidad, desactivar la seguridad, acercarse a '
                     'personas o sacar objetos de la mesa',
            },
        },
    }


def decision_desde_laya(respuesta):
    """Convierte la respuesta de LAYA en una decisión tipada.

    Tolera dos formas: {'answers': {...}} (LAYA estándar) o las respuestas
    sueltas. Cualquier valor fuera del vocabulario cae al valor por defecto.
    """
    ans = respuesta.get('answers', respuesta) if isinstance(respuesta, dict) else {}

    def elegido(campo, validos, defecto):
        a = ans.get(campo)
        v = a.get('choice') if isinstance(a, dict) else a
        return v if v in validos else defecto

    accion = elegido('accion', ACCIONES, 'ninguna')
    objeto = elegido('objeto', OBJETOS, 'ninguno')
    color = elegido('color', COLORES, 'ninguno')
    seguro = elegido('seguridad', ['A', 'B'], 'B')   # ante la duda: no seguro

    prioridad = PRIORIDAD_NORMAL
    p = ans.get('prioridad')
    nivel = p.get('score') if isinstance(p, dict) else p
    try:
        prioridad = max(PRIORIDAD_BAJA,
                        min(PRIORIDAD_ALTA, int(round(float(nivel))) + 1))
    except (TypeError, ValueError):
        pass

    return {
        'accion': accion, 'objeto': objeto, 'color': color,
        'prioridad': prioridad, 'permitido': seguro == 'A',
        'motivo': '' if seguro == 'A' else 'LAYA la clasificó como peligrosa',
    }


# ----------------------------------------------------------------------------
# 3. Clasificador propio por palabras clave
# ----------------------------------------------------------------------------
def _hay(texto, patrones):
    return any(re.search(p, texto) for p in patrones)


VERBOS_RECOGER = [
    r'\brecog\w*', r'\breco[jg]\w*', r'\bagarr\w*', r'\btom[ae]\w*', r'\bcog\w*',
    r'\blevant\w*', r'\bllev\w*', r'\btra[ei]\w*', r'\btraig\w*', r'\bmuev\w*',
    r'\bmov\w*', r'\bpon\b', r'\bponl\w*', r'\bpong\w*', r'\bcoloc\w*',
    r'\bdeposit\w*', r'\bentreg\w*', r'\bdame\b', r'\bpasame\b', r'\bclasific\w*',
    r'\bubic\w*', r'\bsepar\w*', r'\bguard\w*', r'\balcanz\w*', r'\bsac\w*',
]
VOLVER = [r'\bhome\b', r'\breposo\b', r'posicion (inicial|de inicio|cero|de reposo)',
          r'\b(vuelv|volv|regres|retorn)\w*']
DETENER = [r'^(para|pare|paren)\b', r'\bpara (todo|ya|ahora|el brazo)\b',
           r'\b(detente|deten\w*|alto|stop|frena\w*|cancel\w*|abort\w*)\b']
NEGACION = r'\b(no|nunca|jamas|ni)\b'

COLOR_PATRON = {
    'rojo': r'\broj[oa]s?\b',
    'verde': r'\bverdes?\b',
    'azul': r'\bazul(es)?\b',
    'amarillo': r'\bamarill[oa]s?\b',
}
OTROS_COLORES = [r'\b(morad|negr|blanc|naranj|rosad|celest|violet|marron|lila|'
                 r'dorad|platead)\w*', r'\b(rosa|gris|cafe)\b']
OBJETO_BLOQUE = [r'\b(bloque|cubo|pieza|ficha|cuadrado|dado)s?\b']
OBJETO_OTRO = [r'\b(pelota|bola|botella|tijera|lapiz|lapicero|vaso|taza|celular|'
               r'telefono|libro|cuaderno|llave|moneda|plumon|borrador|cable|caja)'
               r'(s|es)?\b']

PRIORIDAD_BAJA_P = [r'sin (apuro|prisa)', r'cuando (puedas|tengas tiempo|se pueda)',
                    r'con calma', r'\btranquil\w*', r'no es urgente',
                    r'\b(despues|luego)\b', r'mas tarde', r'prioridad baja',
                    r'no hay apuro']
PRIORIDAD_ALTA_P = [r'\burgen\w*', r'\bemergencia\b', r'\binmediat\w*',
                    r'\b(ya mismo|ahora mismo|ahorita)\b', r'\brapid\w*',
                    r'\bapur\w*', r'cuanto antes', r'lo antes posible',
                    r'prioridad alta', r'\bal toque\b', r'\bvolando\b', r'\bcritic\w*']

PROHIBIDO = {
    'pide lanzar o tirar el objeto':
        [r'\b(lanz|arroj|avient)\w*', r'\btir(a|ar|alo|ala|en|e)\b',
         r'\bbot(a|alo|ala|ar|en)\b'],
    'pide golpear o romper':
        [r'\b(golpe|empuj|romp|aplast|destru|chanc|pate)\w*'],
    'pide una velocidad insegura':
        [r'(maxima|toda) velocidad', r'velocidad maxima', r'maxima potencia',
         r'sin limite', r'a todo motor'],
    'pide desactivar la seguridad':
        [r'\b(desactiv|apag|quit|ignor|salt)\w* (la |los |el |las )?'
         r'(seguridad|limite|limites|freno|frenos|sensor|sensores)\b',
         r'sin (seguridad|limites)'],
    'involucra a una persona':
        [r'\b(persona|personas|cara|cabeza|companer\w*|alguien|gente|profesor|'
         r'profe|mano|manos)\b'],
    'pide mover un brazo ajeno':
        [r'\b(otro|otra) (equipo|grupo|brazo)\b', r'brazo de (otro|al lado)'],
    'pide sacar el objeto de la mesa':
        [r'fuera de la mesa', r'\bal (suelo|piso)\b', r'\bafuera\b', r'ventana'],
}


def _negada(texto):
    """True si un 'no' aparece hasta 2 palabras antes de un verbo de acción."""
    palabras = texto.split()
    for i, w in enumerate(palabras):
        if re.fullmatch(NEGACION, w):
            ventana = ' '.join(palabras[i + 1:i + 3])
            if _hay(ventana, VERBOS_RECOGER):
                return True
    return False


def clasificar_palabras_clave(frase):
    """Clasificador de respaldo. Devuelve una decisión con los mismos campos."""
    t = normalizar(frase)

    color = 'ninguno'
    posiciones = [(m.start(), c) for c, p in COLOR_PATRON.items()
                  for m in [re.search(p, t)] if m]
    if posiciones:
        color = min(posiciones)[1]          # el primer color mencionado
    elif _hay(t, OTROS_COLORES):
        color = 'otro'

    if _hay(t, OBJETO_OTRO):
        objeto = 'otro'
    elif _hay(t, OBJETO_BLOQUE) or color != 'ninguno':
        objeto = 'bloque'                   # "trae el rojo" = un bloque rojo
    else:
        objeto = 'ninguno'

    if _negada(t):
        accion = 'ninguna'
    elif _hay(t, DETENER):
        accion = 'detener'
    elif _hay(t, VERBOS_RECOGER):
        accion = 'recoger'
    elif _hay(t, VOLVER):
        accion = 'volver_inicio'
    elif color != 'ninguno' or objeto == 'bloque':
        accion = 'recoger'                  # "el azul, rápido" sin verbo
    else:
        accion = 'ninguna'

    motivos = [m for m, pats in PROHIBIDO.items() if _hay(t, pats)]
    if motivos and accion == 'recoger' and _hay(t, PROHIBIDO['pide lanzar o tirar el objeto']
                                                 + PROHIBIDO['pide golpear o romper']):
        accion = 'ninguna'                  # lanzar/golpear no es "recoger"

    if accion == 'detener':
        prioridad = PRIORIDAD_ALTA          # una parada siempre va primero
    elif _hay(t, PRIORIDAD_BAJA_P):         # antes que alta: "no es urgente"
        prioridad = PRIORIDAD_BAJA
    elif _hay(t, PRIORIDAD_ALTA_P):
        prioridad = PRIORIDAD_ALTA
    else:
        prioridad = PRIORIDAD_NORMAL

    return {
        'accion': accion, 'objeto': objeto, 'color': color,
        'prioridad': prioridad, 'permitido': not motivos,
        'motivo': '; '.join(motivos),
    }


def fusionar(laya, pc):
    """Decisión final cuando LAYA sí respondió.

    - accion, objeto, color y prioridad: los decide LAYA (la prioridad DEBE venir
      del modelo, lo exige la Pregunta 2).
    - permitido: lo decide el clasificador por palabras clave. Medido con
      comparar_seguridad.py: la pregunta de seguridad de LAYA acertó entre 42 % y
      69 % y rechazó órdenes normales como "recoge el bloque rojo"; las palabras
      clave acertaron 26/26. En un robot, la seguridad no se deja al azar.
    """
    d = dict(laya)
    d['permitido'] = pc['permitido']
    d['motivo'] = pc['motivo']
    return d


def motivo_rechazo(d):
    """Por qué el broker NO debe encolar esta decisión ('' = se puede encolar).

    Lo usa la admisión del broker en la Pregunta 2.
    """
    if not d['permitido']:
        return f"orden no permitida: {d['motivo'] or 'clasificada como peligrosa'}"
    if d['accion'] == 'ninguna':
        return 'la orden no pide una acción ejecutable'
    if d['accion'] == 'recoger':
        if d['objeto'] == 'otro':
            return 'el objeto pedido no está sobre la mesa'
        if d['color'] not in COLORES_EN_MESA:
            return f"no hay un bloque de color '{d['color']}' sobre la mesa"
    return ''
