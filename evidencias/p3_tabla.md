## Parte B — Órdenes habladas

| # | Lo que se dijo | Lo que transcribió el sistema | Decisión del modelo | Lo que hizo el brazo | ¿Correcta? |
| --- | --- | --- | --- | --- | --- |
| 1 | trae el bloque rojo | Trae el bloque rojo. | recoger · bloque · rojo · prioridad 2 | rojo desde pos_rojo a deposito_rojo · error 4.1 mm | si |
| 2 | lleva el bloque azul, es urgente | Lleva el bloque azul es urgente. | recoger · bloque · azul · prioridad 2 | azul desde pos_azul a deposito_azul · error 4.1 mm | si |
| 3 | Agárrame el bloque amarillo | Agárrame el bloque amarillo. | recoger · bloque · amarillo · prioridad 2 | amarillo desde pos_amarillo a deposito_amarillo · error 4.8 mm | si |
| 4 | Trae la pelota verde | Trae la pelota verde. | recoger · otro · verde · prioridad 2 | nada: rechazada (el objeto pedido no está sobre la mesa) | si |
| 5 | Lanza el bloque verde | Lanza el bloque verde. | ninguna · bloque · verde · prioridad 2 | nada: rechazada (orden no permitida: pide lanzar o tirar el objeto) | si |

Correctas: 5/5

## Parte C — De la voz al movimiento (segundos)

| # | Captura del audio | Transcripción (nube) | Decisión del modelo | Espera en la cola | Percepción | Cinemática inversa | Planificación | Otros* | Total medido |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.06 | 2.46 | 0.17 | 0.01 | 7.98 | 0.16 | 0.03 | 0.06 | 10.92 |
| 2 | 0.03 | 2.58 | 0.14 | 0.01 | 7.99 | 0.17 | 0.03 | 0.05 | 11.01 |
| 3 | 0.06 | 2.94 | 0.15 | 0.01 | 7.98 | 0.02 | 0.02 | 0.05 | 11.24 |
| Promedio | 0.05 | 2.66 | 0.15 | 0.01 | 7.98 | 0.12 | 0.03 | 0.05 | 11.06 |

*Otros: transporte ROS, envío del goal y respuesta del broker (total medido − suma de etapas).

Etapa dominante: **Percepción**, 7.98 s de 11.06 s (72 %).

Figura: p3_desglose.png
