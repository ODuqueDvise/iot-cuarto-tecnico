# 3. Nodo ESP32 (DevKit V1)

## Herramientas

ESP-IDF 5.3 o posterior. La vía más simple es la extensión "ESP-IDF" de VS Code, que instala el conjunto de herramientas.
Alternativa por terminal: clonar `espressif/esp-idf`, ejecutar `install.sh esp32` y luego `. export.sh` en cada sesión.

## Configurar

```bash
cd nodo
cp main/secretos.h.ejemplo main/secretos.h      # SSID, clave, IP del borde, identificador del nodo
cp ../borde/certificados/salida/ca.crt    main/certs/ca.crt
cp ../borde/certificados/salida/nodo1.crt main/certs/nodo.crt
cp ../borde/certificados/salida/nodo1.key main/certs/nodo.key
```

Los certificados se traen desde la Pi con `scp`. Ninguno de estos archivos entra al repositorio.

## Compilar y cargar

```bash
idf.py set-target esp32
idf.py build
idf.py -p /dev/cu.usbserial-0001 flash monitor     # el puerto cambia; `ls /dev/cu.*` lo muestra
```

En el monitor debe verse: Wi-Fi conectado, hora sincronizada con el borde, MQTT conectado y una publicación cada 10 s.
En la Pi, `mosquitto_sub` sobre `cuarto/#` muestra la telemetría y el tema `cuarto/nodo1/estado` queda en `en_linea`.
Al desconectar el nodo, unos 15 s después el intermediario publica `fuera_de_linea` por el mensaje de última voluntad (RC2).

## Qué hace este firmware y qué falta

Hace: Wi-Fi en modo estación, SNTP contra el borde, MQTT 5.0 con TLS y certificado de cliente, última voluntad, telemetría simulada, suscripción a comandos.
Falta (etapas siguientes): lectura de SHT31, ADS1115 y entradas digitales; reglas duras; relés; búfer en LittleFS; cifrado de flash y NVS; modo registrador.

El código no fue compilado por el asistente; puede necesitar ajustes menores según la versión de ESP-IDF.
