# 2. Borde: certificados, InfluxDB y puente

Todo se ejecuta en la Raspberry Pi, dentro de `iot-cuarto-tecnico/borde`, después de `instalar.sh`.

## Certificados

```bash
cd certificados
./crear_ca.sh
./crear_certificado.sh borde 192.168.110.174     # el intermediario; la IP es la fija de la Pi
./crear_certificado.sh borde-puente            # el puente MQTT a InfluxDB
./crear_certificado.sh nodo1                   # el nodo del cuarto
./crear_certificado.sh registrador             # el registrador provisional
sudo install -d -o mosquitto -g mosquitto -m 750 /etc/mosquitto/certs
sudo install -o mosquitto -g mosquitto -m 640 salida/ca.crt salida/borde.crt salida/borde.key /etc/mosquitto/certs/
sudo systemctl restart mosquitto
```

El nombre que se pasa al guion queda como CN del certificado y Mosquitto lo usa como nombre de usuario,
así que debe coincidir con el prefijo del tema en `mosquitto/acl.conf` (`cuarto/nodo1/...`).

Prueba desde la misma Pi, con el certificado del puente:

```bash
mosquitto_sub -h 192.168.110.174 -p 8883 --cafile salida/ca.crt --cert salida/borde-puente.crt --key salida/borde-puente.key -t 'cuarto/#' -v &
mosquitto_pub -h 192.168.110.174 -p 8883 --cafile salida/ca.crt --cert salida/nodo1.crt --key salida/nodo1.key -t cuarto/nodo1/telemetria -m '{"prueba":1}'
```

Debe verse el mensaje. Una publicación con el certificado de `nodo1` a `cuarto/registrador/telemetria` debe ser rechazada en silencio (RNF2).

## InfluxDB

```bash
cd ../influxdb
./configurar.sh        # crea la organización, el depósito "cuarto" con 90 días y un token para el puente
```

El guion imprime el token una sola vez. Guardarlo en `../puente/puente.env`.

## Grafana

Abrir `http://192.168.110.174:3000` desde la red administrativa (usuario `admin`, contraseña `admin`, cambiarla al entrar).
La fuente de datos queda aprovisionada por `grafana/datasource.yaml`; `configurar.sh` la copia con el token a
`/etc/grafana/provisioning/datasources/influx.yaml`.

## Puente MQTT a InfluxDB

```bash
cd ../puente
cp puente.env.ejemplo puente.env && nano puente.env
sudo ./instalar_puente.sh
journalctl -u puente -f
```

Cuando el nodo publique, `influx query 'from(bucket:"cuarto") |> range(start:-10m)'` debe mostrar puntos.

## Registrador CSV

Servicio independiente del puente y de InfluxDB que escribe `/var/lib/registrador/<nodo>_<AAAAMMDD>.csv`, con las mismas
columnas que la captura serie del Mac. Usa el usuario, los certificados y el entorno de Python del puente, y una sesión
persistente de MQTT 5 de una hora: si se reinicia, Mosquitto le entrega lo que llegó mientras tanto. Solo registra
mensajes con hora del nodo y descarta duplicados por marca de tiempo.

Instalación y actualización desde el Mac: `herramientas/nodo.sh registrador` (corre `prueba_registrador.py` en la Pi
antes de instalar). Para traer los archivos del día: `nodo.sh traer`; para validarlos: `nodo.sh validar <csv>`.

## Panel de Grafana

`borde/grafana/nodo_sensor.json` se aprovisiona por archivo (`tablero.yaml`) en la carpeta "Cuarto técnico". Elige la
fuente InfluxDB y el nodo con variables, así que no depende del identificador interno de la fuente de datos. Muestra los
valores actuales, las series de temperatura y punto de rocío (umbrales 27 °C y 15 °C), HR (60 %), corriente media y
máxima, puerta y agua, muestras por hora (120 esperadas a 30 s), retraso respecto de la cuadrícula, estado de los sensores,
muestras sin hora y la salud de la Pi (temperatura del SoC y memoria disponible, que escribe el puente cada 30 s en la
medición `borde`).

Instalación desde el Mac: `herramientas/nodo.sh panel`. Antes de instalar corre cada consulta del tablero contra InfluxDB
en la Pi (`probar_consultas.py`) y se detiene si alguna falla. El tablero queda en `http://<borde>:3000/d/nodo-sensor`.

