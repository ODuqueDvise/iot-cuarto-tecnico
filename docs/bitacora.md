# Bitácora del proyecto

## 2026-10-10

- Propuesta entregada el 4 de octubre (ver `propuesta.pdf`).
- Pedido de componentes en Amazon; llegada estimada el 19 de octubre. El varistor se compra en Bogotá.
- Se adelantan el borde y el firmware base con datos simulados mientras llegan las piezas.
- Cronograma ajustado: línea base del 19 de octubre al 2 de noviembre; umbrales definitivos el 3 de noviembre.
- Usuario del sistema en la Pi: odukec.
- Red: la Pi (192.168.110.174) y el Mac (192.168.110.236) están en la misma subred 192.168.110.0/24, puerta de enlace .1.
  Todavía no hay VLAN de IoT. Pendiente antes de la prueba continua de noviembre (RC1): pasar el puerto de la Pi y el punto
  de acceso de IoT a una VLAN propia; al cambiar la IP del borde hay que reemitir su certificado (crear_certificado.sh borde <ip>).
- Repositorio publicado en https://github.com/ODuqueDvise/iot-cuarto-tecnico (privado).
- Pendiente de medir: memoria disponible en la Pi de 1 GB con Mosquitto, InfluxDB y Grafana arriba.
- Sistema: Raspberry Pi OS sobre Debian 13 (trixie); trae zram propio (905 MB), por eso se retiró zram-tools del instalador.
  La primera instalación quedó detenida en una pregunta interactiva del paquete de claves de InfluxData; el instalador
  ahora corre en modo no interactivo.
- Instalados: InfluxDB 2.9.1, Grafana 13.2.3, Mosquitto, chrony.
- Medición de memoria con InfluxDB y Grafana arriba (sin datos): 667 MB disponibles con la sesión de Warp abierta
  (unos 90 MB de su servidor remoto); sin ella, unos 750 MB. Grafana 203 MB, influxd 95 MB. Supera el umbral de 400 MB:
  Grafana se queda. Temperatura del SoC 55,5 °C en reposo.
- Mosquitto con TLS mutuo en 8883 (se quitó la persistencia duplicada de iot.conf). Prueba superada:
  nodo1 publica en su tema y el puente lo recibe; nodo1 en el tema del registrador es descartado por la ACL;
  conexión sin TLS al 1883 rechazada. Evidencia para RNF2 y RC2.
- InfluxDB configurado (organización y depósito "cuarto", 90 días) y puente instalado como servicio.
  Prueba de punta a punta superada: un mensaje publicado con el certificado de nodo1 llegó a InfluxDB con sus
  seis campos (t, hr, i, puerta, agua, origen) y la etiqueta nodo. Sin "ts" en el mensaje, el puente usó la hora del borde.
- Firmware base del nodo (ESP-IDF 5.5) compilado y cargado en el DevKit V1 al primer intento. Wi-Fi con IP 192.168.110.80,
  hora sincronizada con el chrony del borde (4 s tras obtener IP), MQTT 5.0 con TLS mutuo conectado y telemetría
  simulada cada 10 s. Cada mensaje JSON pesa 111 bytes, menos que los 300 supuestos en la propuesta para estimar el ancho de banda.
- Prueba de última voluntad (RC2): el nodo negocia keepalive de 10 s con MQTT 5 (registro de Mosquitto: p5, k10).
  Medición 1: desconexión física en 1791673023, "exceeded timeout" en 1791673034: 11 s (requisito: menos de 30 s;
  máximo teórico 15 s). Pendiente: dos repeticiones más.
- Decisión: la red 192.168.110.0/24 es la de la casa (desarrollo). La VLAN de IoT se configura en el cuarto técnico al instalar,
  no en la casa. Para que el cambio de red cueste poco: el certificado del borde incluye localhost y 127.0.0.1, el puente se
  conecta por localhost y el nodo verifica el CN "borde" (no la IP). Al mudar el borde solo cambian MQTT_URI y SNTP_SERVIDOR
  en secretos.h y la IP del SAN del certificado.
- Detector SSD-MobileNetV2 (COCO, TF2 Model Zoo, exportado a ONNX en el Mac) medido en la Pi con ONNX Runtime, 4 hilos, entrada 320x320:
  carga del modelo 6,8 s desde la microSD; inferencia media 207 ms (mediana 205, p95 217, 30 corridas); ráfaga de 20 cuadros
  estimada en 4,1 s (RF4). Memoria del proceso: 131 MB pico. Conteo correcto en 3 fotos (0, 1 y 2 personas, umbral 0,5);
  muestra mínima, no es una evaluación de exactitud.
- Memoria con todos los servicios y el puente, sin detector: 488 MB disponibles. Grafana 163 MB más sus procesos de complementos
  (InfluxDB 19, PostgreSQL 8, Loki 7 MB); influxd 43 MB residentes, parte en zram. Con el detector en una ráfaga quedarían unos 360 MB.
- Temperatura del SoC 73 °C justo después de la medición (55 °C en reposo). La Pi 4 empieza a reducir frecuencia hacia 80 °C;
  revisar disipación antes de instalarla en el cuarto técnico.
