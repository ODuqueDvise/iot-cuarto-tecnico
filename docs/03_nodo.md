# 3. Nodo ESP32 (DevKit V1)

## Atajo

`herramientas/nodo.sh` hace todo lo de esta guía con una sola orden y desde cualquier carpeta: encuentra y activa
ESP-IDF, genera `sdkconfig` si falta, revisa que estén `secretos.h` y los certificados, y detecta el puerto del ESP32.
`nodo.sh ayuda` lista las órdenes (compilar, cargar, monitor, capturar, oficial, modos, modo, pruebas).
Las secciones siguientes explican lo que el guion hace por dentro.

## Herramientas

ESP-IDF 5.5 (el nodo se compiló con 5.5.5). La vía más simple es la extensión "ESP-IDF" de VS Code.
Alternativa por terminal: clonar `espressif/esp-idf`, ejecutar `install.sh esp32` y luego `. export.sh` en cada sesión.

## Configurar

En el Mac:

```bash
cd nodo
cp main/secretos.h.ejemplo main/secretos.h      # SSID, clave, IP del borde, identificador del nodo
cp ../borde/certificados/salida/ca.crt    main/certs/ca.crt
cp ../borde/certificados/salida/nodo1.crt main/certs/nodo.crt
cp ../borde/certificados/salida/nodo1.key main/certs/nodo.key
```

Los certificados se traen desde la Pi con `scp`. Ninguno de estos archivos entra al repositorio.
`PERIODO_TELEMETRIA_MS` de `secretos.h` ya no se usa: el periodo está en el menú del nodo.

## Elegir el modo de cada sensor

Menú `Nodo del cuarto técnico` (`idf.py menuconfig`):

- `Periodo de muestreo y registro`: 30 s para la Actividad 2.
- `Modo de cada sensor`: temperatura y HR, corriente, puerta y agua, cada uno en `Real`, `Simulado` o `Ausente`.
  Mientras falten piezas: `Simulado` para ensayar la cadena completa y `Ausente` para entregar solo lo que existe.
  El campo `origen` de cada registro dice `simulado` si algún sensor lo está; esos datos no se entregan.
- `Pines y direcciones` y `Calibración y umbrales`: valores de la tabla de conexiones.

## Compilar y cargar

La primera vez después de este cambio hay que regenerar `sdkconfig` para que tome los nuevos valores por defecto
(partición de aplicación de 1,5 MB y cola de salida MQTT de hasta 3 h). En el Mac:

```bash
cd nodo
rm sdkconfig
idf.py set-target esp32
idf.py build
idf.py -p /dev/cu.usbserial-0001 flash monitor     # el puerto cambia; `ls /dev/cu.*` lo muestra
```

`flash` escribe también la nueva tabla de particiones. En el monitor debe verse: escaneo del bus I2C, Wi-Fi conectado,
hora sincronizada con el borde, MQTT conectado y una línea `REG,...` en cada múltiplo de 30 s del reloj (hh:mm:00 y hh:mm:30).

## Capturar los registros en el Mac (decisión D8)

Cerrar antes el monitor de `idf.py`, porque ambos usan el mismo puerto. En el Mac, con el entorno de ESP-IDF activo
(trae pyserial):

```bash
cd herramientas
python3 capturar_serie.py --puerto /dev/cu.usbserial-0001 --salida ../datos/ensayo.csv
python3 capturar_serie.py --puerto /dev/cu.usbserial-0001 --salida ../datos/oficial.csv --muestras 360
```

Muestra cada registro en pantalla, lo agrega al CSV en cuanto llega y al terminar imprime un resumen: filas,
discontinuidades de `seq`, separación entre marcas de tiempo, celdas vacías y origen.

## Conexiones

| Pieza | Pin de la pieza | ESP32 (por defecto) | Nota |
|---|---|---|---|
| SHT31 | VIN, GND | 3V3, GND | |
| SHT31 | SDA, SCL | GPIO 21, GPIO 22 | Bus compartido con el ADS1115 |
| SHT31 | ADDR | GND | Dirección 0x44 |
| ADS1115 | VDD, GND | 3V3, GND | Con 3,3 V ninguna entrada puede superar 3,6 V |
| ADS1115 | SDA, SCL | GPIO 21, GPIO 22 | |
| ADS1115 | ADDR | GND | Dirección 0x48 |
| ADS1115 | ALRT | GPIO 19 | Señal de conversión lista; pull-up interna |
| ADS1115 | A1 | Punto medio del divisor | Dos resistencias iguales entre 3V3 y GND, con condensador del punto medio a GND (por ejemplo 10 kOhm y 10 µF; verificar en el banco) |
| SCT-013-050 (50 A/1 V, carga interna) | Terminal 1 y 2 del conector de 3,5 mm | A1 y A0 del ADS1115 | A0 ve la señal montada sobre la polarización; la medición es diferencial A0 menos A1 |
| Contacto de puerta | Dos cables | GPIO 27 y GND | Cerrado con la puerta cerrada; abierto o cable cortado se lee como puerta abierta |
| Sonda de agua | Electrodo A | GPIO 25 | Excitación por pulsos de 0,5 ms cada segundo |
| Sonda de agua | Electrodo B | GPIO 34, y 100 kOhm a GND | GPIO 34 es de ADC1 y no tiene pull-down interna |

El SCT-013 se abraza alrededor de un solo conductor de un cordón de prueba; nunca se conecta a la red.
No superar 5 A en ese conductor (unos 600 W a 120 V).

## Qué hace este firmware

- Wi-Fi en modo estación, SNTP contra el borde, MQTT 5.0 con TLS y certificado de cliente, última voluntad (etapa 1).
- Muestreo en una cuadrícula absoluta del reloj sincronizado, sin deriva acumulada; `retraso_ms` registra cuánto tarde
  respecto del instante nominal se tomó la muestra.
- `seq` avanza en cada muestra, haya o no conexión: una pérdida deja un hueco visible.
- Temperatura y HR del SHT31 con verificación de CRC y un reintento; punto de rocío por Magnus.
- Corriente: valor eficaz de la componente alterna en ventanas de 1 s a 860 muestras por segundo; cada registro lleva la
  media y el máximo de las ventanas del intervalo.
- Puerta leída cada 50 ms y sonda de agua cada 1 s, con antirrebote y contadores de aperturas y eventos por intervalo.
- `estado_sensores`: 1 fallo del SHT31, 2 fallo de corriente, 4 fallo de la sonda, 8 sin hora, 16 cuadrícula
  recalculada, 32 sin conexión MQTT al registrar (el mensaje quedó en la cola). Los bits se suman.
- Cada registro sale por el puerto serie (línea `REG,`) y por MQTT. Sin conexión, la cola de salida del cliente
  retiene los mensajes (96 KB, unas 400 muestras, más de 3 h) y los envía al reconectar.
- Cada hora informa la memoria libre y el tamaño de la cola.

Pruebas de los cálculos (CRC, conversiones, punto de rocío, valor eficaz, cuadrícula), en el Mac:

```bash
cd nodo/pruebas
cc -std=gnu11 -I../main prueba_calculos.c ../main/calculos.c -lm -o prueba && ./prueba
```

## Qué falta

Reglas duras, relés, búfer en LittleFS (RNF1), cifrado de flash y NVS, configuración por comandos MQTT (RNF4).

El firmware se compiló sin errores ni advertencias con ESP-IDF 5.5.5 en cuatro combinaciones de modos (todo simulado,
todo real, todo ausente y mixto), pero todavía no se ha probado en el ESP32 ni con los sensores.

## LED de estado

El LED azul de la placa (GPIO 2, `NODO_LED_GPIO`; -1 lo desactiva) indica el estado sin necesidad del monitor serie:

| Patrón | Significado |
|---|---|
| Parpadeo rápido continuo (5 por segundo) | Sin Wi-Fi |
| Parpadeo lento (1 por segundo) | Wi-Fi conectado, pero sin MQTT o sin hora del borde |
| Un destello corto cada 3 s | En línea, sensores bien |
| Tres destellos cortos cada 3 s | En línea, la última muestra trae falla de algún sensor (bits 1, 2 o 4) |
| Encendido fijo 300 ms | Se acaba de registrar una muestra (cada 30 s) |

## Comandos por MQTT (Actividad 3)

El nodo está suscrito a `cuarto/<nodo>/comandos` (QoS 2) y responde en `cuarto/<nodo>/respuestas` (QoS 1). Un comando es un objeto JSON:

| Clave | Valor | Efecto |
|---|---|---|
| `periodo` | entero de 5 a 600 | Nuevo periodo de muestreo en segundos. La tarea de muestreo rehace la cuadrícula y la muestra siguiente lleva el bit 16 (cuadrícula recalculada). El campo `periodo` de la telemetría refleja el valor vigente |
| `led` | `"on"`, `"off"`, `"auto"` | Fuerza el LED de estado encendido o apagado, o devuelve los patrones automáticos |
| `id` | cualquiera | Se devuelve en la respuesta para correlacionar |

Respuesta: `{"id": ..., "ok": true|false, "detalle": "...", "periodo": N}`. Un comando con una clave inválida se rechaza completo y no cambia nada. El periodo compilado (`CONFIG_NODO_PERIODO_S`) vuelve a regir en el siguiente arranque: el cambio no se guarda en memoria no volátil.

Quién puede comandar: la lista de control de Mosquitto (`borde/mosquitto/acl.conf`) solo deja escribir en `comandos` al certificado del puente (`borde-puente`); cada nodo solo lee sus comandos y escribe su telemetría, su estado y sus respuestas. Con TLS mutuo, un cliente sin certificado firmado por la CA del proyecto ni siquiera conecta.

Desde el Mac: `nodo comandos` instala la herramienta y la lista de control en la Pi una vez; después, `nodo comando '{"periodo": 10}'` envía el comando y muestra la respuesta. En la Pi, la herramienta es `/opt/puente/comando.py`.
