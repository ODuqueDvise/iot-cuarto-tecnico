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
  máximo teórico 15 s). Medición 2: 1791675212 a 1791675225, 13 s. Medición 3: 1791675271 a 1791675286, 15 s.
  Rango medido: 11 a 15 s, coherente con 1,5 veces el keepalive de 10 s; cumple RC2 (menos de 30 s) con margen.
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

## 2026-10-11

- Plan de la Actividad 2 revisado (`../Actividad 2/plan_de_trabajo.md`): compra local el martes 13 (SHT31, contacto, sonda),
  captura serie en el Mac en lugar de copia en LittleFS, periodo fijo de 30 s en compilación, consumo con INA226 fuera.
- Firmware del nodo, etapa 2 (N-03): cada sensor en modo real, simulado o ausente (menú "Nodo del cuarto técnico");
  muestreo en cuadrícula absoluta de 30 s; seq por muestra (antes solo avanzaba con MQTT conectado, y el periodo real era
  10 s más el tiempo de publicación); línea CSV por serie; cola de salida MQTT de 48 KB con expiración de 3 h
  (la de fábrica descartaba a los 30 s); estado_sensores por bits; memoria libre cada hora.
- Controladores: SHT31 (0x2400, CRC 0x31), ADS1115 diferencial AIN0-AIN1, ±2,048 V, 860 SPS, ALERT/RDY como conversión
  lista (0x04E0; con 0x04E3 el pin queda en alta impedancia). Comandos y bits contrastados con las hojas de datos.
- Compilado sin advertencias con ESP-IDF 5.5.5 en cuatro combinaciones de modos. Con los controladores reales el binario
  ocupaba el 96 % de la partición de 1 MB: se pasa a la de 1,5 MB (35 % libre). Hay que borrar `nodo/sdkconfig` antes de
  compilar para que tome los nuevos valores por defecto.
- Pruebas de cálculos en el computador (`nodo/pruebas/`): CRC del ejemplo de la hoja de datos, conversiones, punto de rocío,
  valor eficaz con desvío y cuadrícula; todas pasan. Captura serie probada con un nodo simulado en una pseudoterminal.
- Pendiente: cargar en el DevKit con sensores simulados y verificar las líneas REG y el retraso respecto de la cuadrícula;
  ampliar el puente con los campos nuevos (pr, i_max, puerta_n, agua_n, est, retraso_ms, periodo), que hoy ignora.

- Atajo `herramientas/nodo.sh`: activa ESP-IDF, detecta el puerto y compila, carga, monitorea, captura y cambia modos con una orden.
- Primera carga del firmware de la etapa 2 en el DevKit, con sensores simulados. Con la Pi apagada: sin hora (15 s de espera
  agotados) y MQTT con tiempo agotado (esp-tls 0x8006); las líneas REG siguieron saliendo por serie con estado 40 (8 + 32).
  Al encender la Pi: cola de 1699 B enviada al conectar (seis mensajes de unos 283 B), seq continuo del 0 al 9, primera
  muestra con hora a las 10:35:00 con 1 ms de retraso y estado 16. Memoria libre 205 KB antes de TLS.
- Puente (N-04): campos nuevos (pr, i_max como float; puerta_n, agua_n, est, retraso_ms, periodo como enteros; seq sigue
  como float porque ese tipo ya existe en el depósito). Los mensajes sin hora van a la medición telemetria_sin_hora con la
  hora de llegada en nanosegundos: antes recibían la hora del borde en segundos y los que llegaban juntos desde la cola se
  sobrescribían. Pruebas en `borde/puente/prueba_puente.py`; escritura por lotes con dos precisiones verificada contra un
  servidor de prueba. `nodo.sh puente` lo prueba, instala y reinicia en la Pi.
- Puente actualizado en la Pi con `nodo.sh puente`; consulta en InfluxDB: est entero y pr decimal en la medición
  telemetria, con marca 15:53:30 UTC sobre la cuadrícula. El JSON del nodo traía residuos de redondeo en float
  (10.991000175...): ahora redondea en double (pendiente de cargar en el nodo).
- Registrador CSV del borde (N-05): `borde/registrador/`. Probado aquí contra un Mosquitto con TLS mutuo: seis mensajes,
  dos publicados con el servicio detenido (entregados al volver por la sesión persistente) y un duplicado descartado.
- Validador `herramientas/validar_archivo.py`: 360 filas, seq, separación, celdas vacías, origen, bits de estado,
  rangos de RF1, series congeladas, recorte por hora, contraste entre dos archivos y .xlsx. `nodo.sh oficial` lo
  ejecuta al terminar la captura.
- Firmware con redondeo corregido cargado. Hora sincronizada 4,8 s después de la IP, MQTT a los 8,6 s, primera muestra
  11:03:00 con 8 ms de retraso y estado 0. Memoria con TLS conectado: 174,7 KB libres (mínima 169,5 KB). Mensaje de unos
  235 B tras el redondeo. Cola de salida subida de 48 a 96 KB (unas 400 muestras, más de 3 h); queda más de 70 KB libre
  con la cola llena.
- Panel de Grafana (N-06): `borde/grafana/nodo_sensor.json`, 18 paneles, aprovisionado por archivo con variables de fuente
  y nodo. Las consultas se prueban contra InfluxDB en la Pi antes de instalar (`nodo.sh panel`). No probado en Grafana 13.2.3
  todavía: el formato es el clásico (schemaVersion 39), que Grafana migra al cargar.
- Puente: salud del borde cada 30 s (temperatura del SoC y memoria disponible) en la medición `borde`, para el panel y para
  vigilar la reducción de frecuencia hacia 80 °C. Requiere `nodo.sh puente` para llegar a la Pi.

- Tablero de Grafana instalado con `nodo.sh panel` (11 de octubre). Para el ensayo N-07: `nodo.sh capturar` evita el reposo del Mac con caffeinate, `nodo.sh corte [s]` detiene Mosquitto para probar la cola, y el contraste con el CSV del borde se limita al intervalo de la captura.
- `nodo.sh ensayo [min] [s]`: ensayo N-07 sin intervención; el corte de Mosquitto lo programa la Pi con systemd-run (sudo una sola vez al inicio); al final trae el CSV del borde, valida y compara.
- Ensayo N-07 (11 de octubre, 11:25:00 a 14:24:30, sensores simulados, `nodo.sh ensayo`): 360 filas, seq de 0 a 359 sin
  huecos, separación siempre de 30 s, retraso máximo 0 ms. Corte de Mosquitto de 120 s programado en la Pi: cuatro muestras
  (12:55:00 a 12:56:30) registradas sin conexión (bit 32), retenidas en la cola del nodo y entregadas al volver. El CSV del
  registrador del borde coincide con la captura serie en las 360 marcas, incluidas las cuatro del corte: la sesión persistente
  del registrador sobrevivió al reinicio de Mosquitto. Validador: sin fallas. Temperatura máxima del SoC de la Pi durante las 3 h:
  66,2 °C (InfluxDB, medición borde), por debajo de los 80 °C en que reduce frecuencia; no hace falta disipador por ahora.
- Observación: abrir la captura serie reinicia el ESP32 en macOS (seq empezó en 0); esta vez la primera muestra llegó con hora.


## 2026-10-17

- Cierre de la Actividad 2 confirmado: jueves 22 de octubre, 23:59. Calendario del plan rehecho: prueba oficial el martes 20.
- Llegó el SHT3x (sin compra local). Conectado a 3V3, GND, SDA en D21, SCL en D22, ADR a GND. Firmware con temperatura y HR en modo real: el escaneo encuentra 0x44; primeras lecturas 25,35 °C y 45,65 a 46,42 % HR (punto de rocío 12,8 a 13,0 °C), estado 0. Hora sincronizada 0,2 s después de la IP y MQTT a los 3,6 s.
- Llegaron el ADS1115, el contacto magnético, la sonda de agua y el SCT-013. Puerta y agua cargadas en modo real (corriente sigue simulada, por eso origen "simulado").
- Puerta, primera prueba (15:22 a 15:24:30): lógica invertida, 1 con el imán puesto y 0 sin él; el regreso del imán se contó como apertura. Antirrebote y conteo entre muestras correctos. Se descarta invertir por firmware: con contacto abierto en reposo, un cable cortado se leería como puerta cerrada. Desde las 15:26:00 la puerta lee 0 con el imán puesto; falta confirmar 1 al retirarlo y 1 con el cable de D27 suelto.
- `puerta_aperturas` y `agua_eventos` cuentan eventos por intervalo de 30 s y se reinician en cada muestra; no son acumulados.
- Prueba del aliento sobre el SHT3x (15:27:00): HR de 46,05 a 51,34 % y punto de rocío de 14,10 a 15,75 °C; volvió a 46,24 % en la muestra siguiente.
- Sonda de agua (15:28:00): gota entre electrodos, agua 1 y agua_eventos 1, estado 0.
- El contacto magnético solo tiene dos hilos. Se agregó la opción `NODO_PUERTA_INVERTIDA` (apagada por defecto) y la orden `nodo.sh contacto normal|invertido`, para usarla solo si se confirma que el contacto abre con el imán.
- El transformador recibido es SCT-013-050 (50 A/1 V, carga interna), no el SCT-013-005 de la propuesta. Firmware: factor 50000 mA/V, escala del ADS1115 de ±2,048 V a ±0,512 V (configuración 0x08E0; 15,6 µV y 0,78 mA por cuenta; hasta unos 18 A eficaces) y opción `NODO_CT_VUELTAS` para calibrar con varias vueltas. Contenido del informe actualizado (modelo y contacto invertido).
- LED de estado (`led.c`, `NODO_LED_GPIO`, 2 por defecto, -1 lo desactiva): parpadeo rápido sin Wi-Fi; lento sin MQTT o sin hora; un destello cada 3 s en línea; tres destellos si la última muestra trae falla de sensor; fijo 300 ms en cada muestra. Compilado en el contenedor con todos los sensores reales, con el LED activo y desactivado, sin advertencias en main/.
- Corriente en modo real (16:45 a 16:49): piso de ruido sin carga 0,002 A (media y máximo). Bombillo LED de 8,8 W encendido hacia las 16:46:25: la muestra de 16:46:30 trae media 0,017 A y máximo 0,098 A (encendido dentro del intervalo); desde 16:47:00, estable en 0,096 a 0,098 A, unas 48 veces el piso de ruido. Con 120 V nominales implica un factor de potencia cercano a 0,76, plausible para un bombillo LED. Sin calibración contra pinza: la pinza no resuelve cargas de este tamaño y no hay carga resistiva grande. Temperatura recuperada a 25,7 a 26,1 °C tras el calentamiento de las 16:04.
- Ensayo N-15 de 1 h con los cinco sensores en modo real (`datos/captura_20261017_1650.csv`, 16:51:00 a 17:50:30): 120 filas, seq 0 a 119 sin huecos, origen "sensor" en todas, ningún bit de estado, retraso de 7 a 14 ms. Validador: sin fallas. Temperatura 25,4 a 26,2 °C, HR 50,9 a 56,3 %, punto de rocío 15,1 a 16,4 °C. Corriente: 0,002 A apagado y 0,093 a 0,098 A con el bombillo LED, con medias intermedias en los intervalos de cambio. Puerta: 5 aperturas, incluida una corta dentro de un intervalo (17:05:30, puerta 0 y 1 apertura). Agua: 6 eventos; en 17:40:00 y 17:42:00 se contó un evento nuevo con el estado ya en 1, gotas nuevas puestas a esas horas (confirmado); sin oscilación de la sonda, no se agrega histéresis.
- Contraste del ensayo N-15 con el CSV del registrador del borde: 120 marcas en común, sin diferencias. `nodo.sh validar` ahora resuelve rutas relativas desde la carpeta del proyecto.
- Sin referencias: el bombillo solo indica 8,8 W, 110 a 240 V, 50/60 Hz (sin corriente ni factor de potencia) y no hay termohigrómetro. El informe declara la corriente sin calibrar con una cota inferior (8,8 W / 120 V = 0,073 A frente a 0,097 A medidos) y la exactitud de temperatura y HR como la del fabricante. Fig. 1 y verificación previa (Tabla IV) agregadas al borrador; protocolo de carga cambiado a tres ciclos de 5 min del bombillo.
- Ronda adversarial del informe (18:00): corregidos el modelo de corriente (se pidió el de 5 A; las dos unidades recibidas son de 50 A), la "cota" de corriente (es plausibilidad, no cota), SHT31 a SHT3x (el módulo solo dice SHT3X; exactitud citada: la del SHT30), cola MQTT "unas 3 h", protocolo sin hielo y con botella cerrada. Retirado el argumento de punto de rocío estable: durante el calentamiento del 16:04 subió de 14 a 18,6 °C (retardo del elemento de humedad). Pendientes: alejar el SHT3x del ESP32 y medir la diferencia; comprobar que secretos.h, certs y puente.env nunca entraron al historial antes de hacer público el repositorio; enviar la pregunta al profesor sobre "pantalla"; evidencias (fotos, capturas, video) el martes.
- El sobre del sensor dice SHT31-D (la serigrafía del módulo solo dice SHT3X): el informe vuelve a SHT31 y cita la exactitud del SHT31.

## 2026-10-18

- Decisión: no se pregunta al profesor por "visualizar en pantalla"; se refuerza la evidencia. El informe describe el conjunto como estación de medición (nodo, computador del canal serie y borde). `capturar_serie.py` muestra cada registro como fila de una tabla con rótulos (estado en palabras, contadores entre paréntesis, cabecera cada 30 filas); el CSV no cambia. Probado con un puerto en bucle. Lista de evidencias para el martes en `Actividad 2/evidencias/LEEME.md`.

## 2026-10-20

- Prueba oficial (`datos/oficial_20261020_0837.csv`, 08:38:00 a 11:37:30): 360 filas, seq 0 a 359, origen "sensor", sin bits de estado, retraso 2 a 7 ms. Sin estímulos salvo tres aperturas de puerta (08:40, 09:08, 09:29; abierta desde 09:29 hasta el final). Corriente 0,001 A todo el tiempo; sin agua. Temperatura 22,4 a 24,7 °C (mañana), HR 48,9 a 56,4 %. Se entrega como prueba de registro de 3 h; la respuesta a estímulos se documenta con los ensayos del 17 de octubre.
- Videos (`Actividad 2/videos/`): IMG_7055.MOV (79 s, celular, montaje completo: válido); primera grabación de pantalla de 12:56 (24 s) descartada: sin filas y con terminal de otros proyectos; segunda grabación de 13:18 (120 s) válida: Grafana, `tail` en la Pi y tabla de la captura con la misma fila 13:20:00 "abierta(1)" en los tres, panel en "Abierta". Cuadros extraídos en `evidencias/_cuadros_tmp/` (borrar al final).
- Borrador completo del informe (7 páginas, 3 pendientes: contraste con el borde del 20, enlaces de los videos, decisión sobre el código). Figuras 2 a 4 generadas por `figuras.py` desde los CSV del repositorio y los cuadros del video. `informe.js`: las tablas ya no se parten entre páginas (keepNext en cada celda), porque una tabla partida seguida de sección continua se superponía al texto. Exactitud del SHT31 citada como ±0,2 °C y ±2 % HR típicos (verificada en la ficha del distribuidor; confirmar en la hoja de datos). `datos/oficial_20261020_0837.xlsx` generado.
- Contraste de la prueba oficial con el CSV del registrador del borde (`datos/borde/nodo1_20261020.csv`): 360 marcas en común, sin diferencias.
- Repositorio público, etiqueta `actividad2-entrega` en el commit 0ac5cfe (verificado desde el contenedor: sin secretos versionados). Referencia [12] del informe. Video único `Actividad 2/videos/nodo_sensor_evidencia.mp4` (1080p, 200 s, sin audio): montaje (79 s) y estación en funcionamiento (120 s). Intermedios en `videos/_tmp/` y cuadros en `evidencias/_cuadros_tmp/`: borrar al final.
- Video publicado como no listado: https://youtu.be/wpJ49keyvAI (referencia [13]). El informe no tiene marcadores pendientes; 7 páginas. Falta la revisión independiente del miércoles.
- Ronda adversarial independiente (revisor separado con PDF, CSV y enunciado): 1 error factual (apertura de las 09:08 duró 2 min, no 30 s), dos afirmaciones sobre HR y punto de rocío contradichas por los datos (retiradas: las fluctuaciones de HR no siguen a la temperatura, r=0,05, y el punto de rocío las sigue, r=0,96), cifra de corriente inconsistente (unificada en 0,094 A y FP 0,78), figura huérfana, sin captura de pantalla. Corregido todo lo de severidad alta y media: Fig. 2 nueva (pantalla de la estación), Fig. 3 con rótulos sobre la foto, figuras renumeradas por orden de cita, coma decimal en los ejes, kB, Tabla III con los archivos del borde, retraso explicado como fase entre el planificador (10 ms) y el reloj SNTP, curva de la primera hora explicada como calentamiento del montaje, argumento de plausibilidad acotado (descarta subestimación, no sobreestimación), armónicos del bombillo a 860 muestras/s, eventos de agua 4 a 6 matizados, conclusión del calor corregida (40 min de recuperación), referencias alineadas a la izquierda. SBAS444E dic. 2024 confirmado en TI. Resultado: 7 páginas, sin pendientes.
- Actividad 3 (cierre jueves 29 de octubre, 12:44): un solo video de máximo 6 min y 100 MB sobre el sistema de transmisión de datos. Recurso registrado en `Actividad 3/recurso_leccion4.md` (lección 4 de IoT for Beginners, con la correspondencia con el proyecto) y análisis en `Actividad 3/analisis_actividad3.md`: huecos (nube frente a borde local, comandos sin interpretar, justificación comparada MQTT/HTTP/CoAP y Wi-Fi/LoRa/BLE/celular, peso del video, narración) y estructura propuesta del video.

## 2026-10-20 (tarde)

- Actividad 2 entregada. Decisiones para la Actividad 3: sin nube (se defiende el borde local), con comandos, voz propia en el video.
- Firmware: comandos JSON en `cuarto/<nodo>/comandos` (`periodo` 5 a 600 s con cuadrícula nueva y bit 16; `led` on/off/auto) y respuesta en `cuarto/<nodo>/respuestas`. `borde/comandos/comando.py` envía y espera la respuesta con el certificado del puente; `acl.conf` autoriza a cada nodo a escribir en sus respuestas; `nodo.sh comandos` instala y `nodo.sh comando` envía. Compilado en el contenedor sin advertencias; falta cargar y probar en el nodo.

## 2026-10-23

- Comandos probados en el nodo (18:48): `{"led":"on"}` y `{"led":"auto"}` aplicados con respuesta en menos de 20 ms; `{"periodo":10}` aplicado, la muestra siguiente (18:49:00) con bit 16 y las siguientes cada 10 s. `nodo comandos` instaló comando.py y la lista de control en la Pi.
- Observación: en el primer minuto tras el arranque la corriente marca 0,067 A sin carga y un máximo de 2,025 A en una ventana (18:47:30 a 18:48:00); después baja a 0,002 A. Coincide con la asociación Wi-Fi y el apretón TLS, que cargan la alimentación de 3,3 V. Para el video, esperar 2 min tras arrancar antes de mostrar la corriente. Mejora pendiente: descartar las ventanas del primer minuto o marcarlas.
- Guion del video (`Actividad 3/guion_video.md`): 8 tramos, 5 min 40 s objetivo, texto guía para la voz, preparación, lista de verificación de la rúbrica y comando de ensamblaje a menos de 100 MB. Láminas 1 a 5 en `Actividad 3/laminas/` (generadas por `hacer_laminas.py`).

## 2026-10-29

- Grabaciones de pantalla (14:50 a 15:31) en `Actividad 3/videos/`: cinco con voz (tramos 1 a 5) y tres mudas (comandos, corte de Mosquitto de 60 s a las 14:29:42, lámina de resultados). Corte verificado en pantalla: filas 49 y 50 (14:30:00 y 14:30:30) con "sin MQTT", fila 51 limpia, journal con Stopped 14:29:42 y Started 14:30:43, Grafana de 58 a 61 muestras al volver. Las filas 41-42 y 45-46 con "sin MQTT" son de dos cortes de ensayo previos (14:26 y 14:28), antes de grabar.
- Montaje: parte narrada recortada de silencios (4:23) y parte muda remontada desde las grabaciones originales; voz grabada sobre ella (toma 1, 2:26 de voz para 1:30 de video). Se decidió asumir el exceso: la parte muda se alargó con metraje real al ritmo de la voz. Video final `Actividad 3/videos/DuqueCantor_IoT_Actividad3.mp4`: 6 min 57 s, 15,9 MB, 1080p. La correspondencia voz-imagen de la parte final (desde 4:23) se fijó por duraciones de los bloques, sin transcripción: no validada por escucha.
- Entre 1:08 y 1:09 de la grabación de 14:22 aparece el historial de comandos del terminal con rutas de otros proyectos; ese segundo no entra en el montaje. Intermedios en `videos/_tmp/`, `_v2/`, `_v3/` y cuadros en `videos/_cuadros/`: borrar al final.

## 2026-10-31

- Actividad 3 entregada el 30 (plazo ampliado): video de 6 min 57 s, LEEME con enlaces, etiqueta `actividad3-entrega`.
- Actividad 4 (cierre jueves 5 de noviembre, 23:53): informe de máximo 8 páginas sobre almacenamiento y procesamiento. Análisis en `Actividad 4/analisis_actividad4.md`. El recurso de la unidad (agricultura inteligente, ThingSpeak por HTTP) define el procesamiento como estadística descriptiva, correlaciones, día y noche y regresión; eso se suma al filtrado y la agregación. Decisión: tareas Flux en InfluxDB más un procesador en Python en la Pi, y análisis fuera de línea para el informe.
- Inventario del depósito `cuarto` (InfluxDB v2.9.1): telemetría del 10 y 11 (prueba y simulado), 17 (mezcla), 20, 23 y 29 de octubre, unas 1.900 muestras, todas de día. Los campos en InfluxDB son los cortos del JSON (`t`, `hr`, `pr`, `i`...), no los del CSV; `seq` quedó como flotante. Nodo encendido desde hoy hasta el miércoles 4 para tener noches.
- `borde/procesamiento/`: `procesador.py` (normalizar, filtrar por origen, deduplicar, rangos, arranques con corriente retirada 90 s, fallos del nodo, huecos por `seq`, histéresis de agua, potencia aparente, eventos; máscara `calidad`), `prueba_procesador.py` (hechos de los CSV reales: 9 arranques el 20, 49 simuladas el 17, 2 cuadrícula y 7 tardías el 29; pasa con pandas 2.3 y 3.0), tareas Flux `agregado_5m`, `resumen_1h`, `calidad_1h`, instalador (depósito `cuarto_procesado` sin límite, token propio, temporizador cada 10 min), `analisis.py` (descriptiva, correlaciones, día y noche, regresión con referencia ingenua). `nodo.sh procesamiento` y `nodo.sh procesar`. Documentado en `docs/05_procesamiento.md`. Pendiente: instalar en la Pi y verificar las tareas Flux (sintaxis no probada contra el servidor).
- Con los datos actuales (tres sesiones cortas de días distintos) la regresión de temperatura a 30 min es peor que la persistencia (RMSE 0,87 frente a 0,33 °C): no hay continuidad temporal. Se repite con la captura larga.

## 2026-10-31 (tarde)

- Plataforma de procesamiento instalada en la Pi con `nodo procesamiento`: depósito `cuarto_procesado` (sin límite), token del procesador, `/opt/procesador` con pandas 2.3.3, `procesador.timer` cada 10 min, tareas `agregado_5m`, `resumen_1h` y `calidad_1h`. Primera versión de las tareas falló en la segunda corrida ("type conflict: bool != int"): en Flux una variable compartida no admite `_value` de tipos distintos en pipelines diferentes. Corregido con un `from()` por grupo de campos (`leer(campos:)`); `agregado_5m` confirmada con `success` y `puerta_fraccion` escrita.
- Fallas del instalador corregidas: comprobación de archivos de `puente` con `sudo test -f` (antes creaba un token repetido; queda uno sobrante "procesador" en `influx auth list`, borrar al final); escritura a InfluxDB con tiempo de espera de 120 s y lotes de 500 puntos (la corrida de 24 h expiró a los 10 s tras reiniciar Grafana).
- Grafana: fuente "InfluxDB procesado" (token de solo lectura de los dos depósitos, `datasource_procesado.yaml`) y tablero `procesado.json` (generado por `generar_procesado.py`, 15 paneles: agregados, calidad, procesador, eventos, antes y después de la corriente). Verificado: los agregados de 5 min se ven; "antes y después" muestra el pico de 300 mA del arranque de las 12:57 en la cruda y no en la limpia. `calidad_1h` y `resumen_1h` sin datos hasta su primera corrida horaria. Tabla de eventos corregida con `group()` (pendiente de reinstalar).
- Nodo encendido desde las 12:57 del 31; debe seguir sin reinicios hasta el miércoles 4 para tener noches. Plan: lunes esqueleto del informe (metodología y justificación), miércoles `nodo traer`, procesador y análisis sobre la captura completa, jueves ronda adversarial y entrega (cierre 23:53).

## 2026-11-05

- Captura continua cerrada: 31 oct. 12:57 a 4 nov. 23:59 (107 h), 12.771 muestras de 12.845 posibles (99,4 %). Incidentes del 4 de noviembre: 18:03 a 19:04 el nodo sin intermediario (última voluntad en Mosquitto a las 18:03:31; la Pi, el intermediario y el puente siguieron, la Pi tiene un solo arranque desde el 10 de octubre y no tiene batería); 123 muestras entregadas desde la cola. 19:42 a 20:19 el nodo sin energía (74 muestras sin registrar, arranque a las 20:19 con seq 3 y cuadrícula); el puente dejó de escribir la salud del borde 17 min (20:12 a 20:29). Hipótesis más consistente: corte en el circuito del router y del nodo, no en el de la Pi. Carga del transformador durante la captura: un televisor.
- Procesador: evento "apagado" (lapso sin muestras antes de un arranque, con muestras sin registrar) y, en modo InfluxDB, lectura de 3 h de contexto antes de la ventana para ver arranques, huecos y apagados que empiezan antes (antes solo 90 s: un apagado largo pasaba inadvertido en el temporizador). Pendiente: reinstalar en la Pi y reprocesar la captura completa.
- Ronda adversarial independiente del informe: 2 hallazgos altos (293 muestras del 3 de noviembre ausentes porque el CSV se trajo a las 21:33 antes de cerrar el día, corregido al traerlo de nuevo; R² 0,92 desactualizado), 11 medios (celda de la Tabla IV, flecha errada en la Fig. 1, tamaño del CSV diario 265 kB y no 370, "642 corridas" calculadas y no medidas, consumo en espera medido de 1 a 5 y no de 0 a 6, "error cuadrático medio" por su raíz, dos sesiones de octubre y no tres, etc.), 6 bajos. Todo corregido. Regresión final: a 30 min 0,16 frente a 0,16 °C de persistencia, a 1 h 0,26 frente a 0,24, a 6 h empate en 0,71.
- Informe final: 8 páginas, `Actividad 4/borrador/DuqueCantor_IoT_Actividad4_Informe.pdf`. LEEME en `Actividad 4/LEEME_entrega.txt`. Salidas del procesador y del análisis en `datos/procesado/` y `datos/analisis/`.
- Segunda ronda adversarial (sobre la versión corregida): 1 hallazgo alto real, el temporizador con ventana de 30 min y los agregados con 20 min no incorporaban las muestras entregadas tarde desde la cola (las de 18:03 a 18:50 del 4, entregadas a las 19:04): el crudo las tenía, el procesado no, y la energía de esa hora salía incompleta en el tablero. Corregido: ventana del procesador 3 h (la cola del nodo), agregados 3 h 20 min, horarias 4 h; `tareas/rehacer.sh` vuelve a correr las tareas sobre un rango. Nivel limpio regenerado a las 08:12; agregados de la captura por rehacer. Medios: la hipótesis del incidente rebajada a lo que los registros sostienen; la comparación de la regresión "tres primeros días" corregida a "hasta el 3 de noviembre a las 21:40" sin atribuir la pérdida de ventaja al corte; rótulos de la Fig. 1. Bajos corregidos (frase sobre variantes no reportadas, "-0 %", pies de tabla y figura, repetición de "no es X sino Y").

## 2026-11-06

- Actividad 5 (cierre jueves 12 de noviembre, 23:53): video de máximo 7 min con la plataforma de visualización y análisis. Análisis en `Actividad 5/analisis_actividad5.md`. Recursos: guía de Intuz (16 herramientas), unidad 3 (seguridad por diseño, Ley 1581, técnicas de análisis básico y procedimiento de siete pasos) y dos tutoriales de Power BI con Azure (archivado y de hacia 2015). De las cinco plataformas que compara la unidad 3, Google Cloud IoT Core, IBM Watson IoT Platform y AWS IoT Analytics ya están retiradas; el streaming en tiempo real de Power BI se retira el 31 de octubre de 2027. Decisión: Grafana en el borde, alertas por correo, narración en vivo.
- Pi con la plataforma completa: 424 MB disponibles de 905, 136 MB en zram; salida a Internet confirmada; Grafana sin SMTP y con acceso anónimo apagado (valores por defecto).
- Línea base 31 oct. a 4 nov. contra ASHRAE: temperatura 21,4 a 24,6 °C, HR hasta 59,8 %, punto de rocío hasta 14,8 °C, ninguna muestra fuera de norma; 3 aperturas de puerta, sin agua.
- `borde/grafana/generar_operacion.py`: tablero `operacion` (31 paneles en tres franjas: ahora, 24 h, análisis) y seis reglas de alerta con correo; `instalar_operacion.sh`, `correo.conf`, `correo.env.ejemplo`; `probar_consultas.py` prueba también anotaciones, admite rango y mide tiempos; `nodo.sh operacion`. Viaja también `procesado.json` con la tabla de eventos corregida (`group()`, pendiente desde el 31). Documentado en `docs/06_visualizacion.md`. Pendiente: instalar y probar contra el servidor (consultas Flux, anotaciones y aprovisionamiento de alertas sin probar).

