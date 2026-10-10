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
