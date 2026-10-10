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
