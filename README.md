# Gran Reto JetCobot - Grupo X

## Integrantes
* Daniela Valeria Ricapa Adrian
* Hugo Javier Barboza Hernandez
* Cielo Camyla Valle Cristobal
* Italo Alejandro Navarrete Pinedo

## Arquitectura de Red
* ROS_DOMAIN_ID=112

## Instrucciones de Ejecución
1. Configurar canal de red: export ROS_DOMAIN_ID=112
2. Leer variable de entorno: export GOOGLE_API_KEY="tu_clave_aqui"
3. Compilar: colcon build y source install/setup.bash
4. Ejecutar el transcriptor: os2 run reto_final_nodos transcriptor_voz
5. Ejecutar el intérprete: os2 run reto_final_nodos interprete_ordenes --ros-args -p url_laya:="http://[IP_LAYA]:5000/predict"
6. Ejecutar el brazo (worker): os2 run arm_broker broker
"@ | Out-File -FilePath "README.md" -Encoding utf8


# 7. Inicializar Git y avisar de éxito
git init
Write-Host "
¡Estructura creada exitosamente en C:\Users\danie\ESAN\2026-2\ROBOTICA\parcial!" -ForegroundColor Green
@"
# Gran Reto JetCobot - Grupo X

## Integrantes
* Daniela Valeria Ricapa Adrian
* Hugo Javier Barboza Hernandez
* Cielo Camyla Valle Cristobal
* Gabriel
* Italo Alejandro Navarrete Pinedo
* Nahim
* Sebastián

## Arquitectura de Red
* ROS_DOMAIN_ID=112

## Instrucciones de Ejecución
1. Configurar canal de red: export ROS_DOMAIN_ID=112
2. Leer variable de entorno: export GOOGLE_API_KEY="tu_clave_aqui"
3. Compilar: colcon build y source install/setup.bash
4. Ejecutar el transcriptor: ros2 run reto_final_nodos transcriptor_voz
5. Ejecutar el intérprete: ros2 run reto_final_nodos interprete_ordenes --ros-args -p url_laya:="http://[IP_LAYA]:5000/predict"
6. Ejecutar el brazo (worker): ros2 run arm_broker broker

## Videos
- P2 — Un pedido por integrante: <enlace>
- P3 — Modo texto sin internet: <enlace>