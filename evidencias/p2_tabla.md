| # | Cliente | Frase | Color | Posición | Resultado del worker | Éxito (visual) | Error FK (mm) | Vía |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Cielo | trae el bloque rojo | rojo | pos_rojo | ok: rojo desde pos_rojo a deposito_rojo · error 7.3 mm | si | 7.3 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo |
| 2 | Italo | lleva el bloque azul urgente | azul | pos_azul | fallo: error inesperado: InvalidHandle: cannot use Destroyable because destruction was requested | si | 1.9 | moveit+agarre_final_directo+subida_directo+deposito_azul_final_directo |
| 3 | Cielo | trae el bloque rojo | rojo | pos_rojo | ok: rojo desde pos_rojo a deposito_rojo · error 7.1 mm | si | 7.1 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo |
| 4 | Cielo | trae el bloque rojo | rojo | pos_rojo | ok: rojo desde pos_rojo a deposito_rojo · error 7.8 mm | si | 7.8 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo |
| 5 | Italo | lleva el bloque azul urgente | azul | pos_azul | ok: azul desde pos_azul a deposito_azul · error 7.8 mm | si | 7.8 | moveit+agarre_final_directo+subida_directo+deposito_azul_final_directo |
| 6 | Daniela | trae el bloque verde | verde | pos_amarillo | ok: verde desde pos_amarillo a deposito_verde · error 4.2 mm | si | 4.2 | moveit+deposito_verde_final_directo |
| 7 | Hugo | agarra el bloque amarillo | amarillo | pos_verde | ok: amarillo desde pos_verde a deposito_amarillo · error 5.5 mm | si | 5.5 | moveit |
| 8 | Cielo | trae el bloque azul | azul | pos_azul | ok: azul desde pos_azul a deposito_azul · error 8.2 mm | si | 8.2 | moveit+agarre_final_directo+subida_directo+deposito_azul_final_directo |
| 9 | Cielo | trae el bloque amarillo | amarillo | pos_amarillo | ok: amarillo desde pos_amarillo a deposito_amarillo · error 2.8 mm | si | 2.8 | moveit |
| 10 | Cielo | trae el bloque rojo | rojo | pos_rojo | ok: rojo desde pos_rojo a deposito_rojo · error 7.5 mm | si | 7.5 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo |
| 11 | Cielo | trae el bloque verde | verde | pos_verde | ok: verde desde pos_verde a deposito_verde · error 7.5 mm | si | 7.5 | moveit+deposito_verde_final_directo |
| 12 | Cielo | trae el bloque rojo | rojo | pos_rojo | ok: rojo desde pos_rojo a deposito_rojo · error 6.6 mm | si | 6.6 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo |
| 13 | Cielo | agarra el bloque azul | azul | pos_rojo | ok: azul desde pos_rojo a deposito_azul · error 7.2 mm | si | 7.2 | moveit+preagarre_articular+sobre_el_bloque_final_directo+agarre_final_directo+subida_directo+deposito_azul_final_directo |

Intentos: 13 · marcados a la vista: 13
Tasa de éxito: 13/13 = 100 %
Error FK (mm): mediana 7.2 · media 6.2 · máximo 8.2 (n=13)
