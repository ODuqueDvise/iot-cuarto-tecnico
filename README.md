# Sistema IoT de monitoreo y control ambiental de un cuarto técnico

Proyecto de curso de Internet de las Cosas (Maestría en Inteligencia Artificial, Universidad de La Salle, 2026-2).
La propuesta entregada está en `docs/propuesta.pdf`; este repositorio contiene lo que se construye a partir de ella.

## Estructura

- `borde/`: todo lo que corre en la Raspberry Pi 4 (1 GB, microSD de 16 GB).
  - `instalar.sh`: instalación del sistema base, Mosquitto, InfluxDB 2, Grafana y chrony.
  - `sistema/`: zram, registros del sistema en memoria y parámetros del núcleo.
  - `mosquitto/`: intermediario MQTT con TLS mutuo y listas de control por tema.
  - `certificados/`: autoridad propia y emisión de certificados por dispositivo.
  - `influxdb/`: configuración ajustada a 1 GB y creación del depósito con retención de 90 días.
  - `grafana/`: aprovisionamiento de la fuente de datos.
  - `puente/`: servicio que pasa la telemetría de MQTT a InfluxDB, escribiendo por lotes.
- `nodo/`: firmware ESP-IDF del nodo ESP32 (DevKit V1). En esta etapa publica telemetría simulada.
- `herramientas/`: guiones de medición.
- `docs/`: guías paso a paso y bitácora.

## Estado

Etapa 1 (10 a 18 de octubre): borde completo sin sensores y firmware base con datos simulados.
Los sensores y actuadores llegan el 19 de octubre. Ver `docs/bitacora.md`.

## Orden de trabajo

1. `docs/01_preparar_raspberry.md`: tarjeta, primer arranque, IP fija.
2. `docs/02_borde.md`: instalación, certificados, InfluxDB, puente.
3. `docs/03_nodo.md`: compilar y cargar el firmware.

## Decisiones

- Paquetes nativos en lugar de Docker, por la memoria de 1 GB.
- ESP-IDF en lugar de Arduino, porque el nodo debe hablar MQTT 5.0 y cifrar la flash y el NVS.
- Una sola etiqueta en InfluxDB (`nodo`) para mantener baja la cardinalidad.
- La agrupación de escrituras ocurre en el puente, con un intervalo de 10 s, porque el detector de anomalías lee de la base de datos.

## Seguridad

Las claves privadas, los certificados emitidos y `nodo/main/secretos.h` están excluidos del repositorio por `.gitignore`.
No subir `borde/certificados/salida/` ni `borde/puente/puente.env`.
