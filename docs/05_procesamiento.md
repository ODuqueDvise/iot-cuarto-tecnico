# 5. Plataforma de almacenamiento y procesamiento (Actividad 4)

## Almacenamiento por niveles

| Nivel | Dónde | Qué | Retención | Quién escribe |
|---|---|---|---|---|
| Crudo | InfluxDB 2, depósito `cuarto` | `telemetria` (una fila por muestra, campos cortos del JSON: `t`, `hr`, `pr`, `i`, `i_max`, `puerta`, `puerta_n`, `agua`, `agua_n`, `est`, `retraso_ms`, `periodo`, `seq`, `origen`), `estado` (en línea), `borde` (salud de la Pi) | 90 días | puente (`borde/puente`) |
| Crudo, canal independiente | `/var/lib/registrador/<nodo>_<AAAAMMDD>.csv` | las mismas muestras con nombres largos | hasta borrar | registrador (`borde/registrador`) |
| Procesado | InfluxDB 2, depósito `cuarto_procesado` | `telemetria_limpia`, `eventos`, `procesador`, `telemetria_5m`, `telemetria_1h`, `calidad_1h` | sin límite | procesador y tareas Flux |

El token del puente solo escribe en `cuarto`; el del procesador lee `cuarto` y escribe `cuarto_procesado`. Grafana lee los dos.

## Flujo

```
nodo --MQTT/TLS--> Mosquitto --> puente --> cuarto (crudo)
                                                 |
                             cada 10 min: procesador.py (ventana de 3 h, idempotente)
                                                 v
                              cuarto_procesado/telemetria_limpia + eventos + procesador
                                                 |
                   cada 5 min: agregado_5m (Flux)   cada hora: resumen_1h, calidad_1h (Flux)
                                                 v
                                   telemetria_5m, telemetria_1h, calidad_1h --> Grafana
```

## Procesador (`borde/procesamiento/procesador.py`)

Pasos, en orden, cada uno con su conteo en el resumen de la corrida:

1. **Normalizar**: tipos canónicos (hora en UTC, enteros, booleanos, flotantes). Resuelve que `seq` quedó como flotante en el crudo.
2. **Filtrar por origen**: solo `origen == "sensor"`; las muestras `prueba` y `simulado` de las pruebas de integración (10, 11 y 17 de octubre) no entran.
3. **Deduplicar** por nodo y marca de tiempo (se conserva la última recibida).
4. **Validar rangos**: temperatura de -10 a 60 °C, humedad de 0 a 100 %, corriente de 0 a 20 A, retraso de 0 a 5000 ms, punto de rocío no mayor que la temperatura. El valor fuera de rango se retira; la muestra queda marcada.
5. **Marcar arranques**: `seq == 0` o `seq` menor que el anterior. En los 90 s siguientes la corriente es la del propio nodo (asociación Wi-Fi y apretón TLS), no la de la carga: se retira.
6. **Retirar fallos del nodo**: bits 1, 2 y 4 de `est` (SHT31, corriente, sonda de agua) retiran el valor afectado; los bits 8, 16 y 32 (sin hora, cuadrícula, sin MQTT) pasan a la máscara `calidad` sin tocar el valor.
7. **Huecos**: un salto en `seq` dentro del mismo arranque; se cuenta cuántas muestras faltaron. El cambio de periodo por comando no es un hueco.
8. **Histéresis de agua**: `agua` en una sola muestra aislada se toma como rebote de la sonda y se suprime (`agua_f`).
9. **Derivar**: potencia aparente `potencia_va = i × 120 V` y `energia_vah` por muestra. No se convierte a vatios porque el factor de potencia de la carga del cuarto no se conoce.
10. **Eventos**: aperturas de puerta, presencia de agua, arranques, huecos y tramos de entrega tardía, con inicio, fin y duración.

Máscara `calidad` (suma de bits): 1 fuera de rango, 2 arranque, 4 fallo de sensor, 8 sin hora, 16 cuadrícula recalculada, 32 entrega tardía, 64 hueco antes, 128 rebote de agua suprimido.

Pruebas: `python3 prueba_procesador.py` fija hechos conocidos de los CSV de `datos/` (por ejemplo, nueve arranques el 20 de octubre, 49 simuladas el 17, siete tardías el 29).

## Tareas Flux (`borde/procesamiento/tareas/`)

- `agregado_5m` (cada 5 min, relee 3 h 20 min): media de `t`, `hr`, `pr`, `i`, `potencia_va`; máximos de `t`, `hr`, `i`; mínimos de `t`, `hr`; fracción de tiempo con puerta abierta y con agua; energía de la ventana; número de muestras.
- `resumen_1h` (cada hora): lo mismo por hora a partir de los agregados de 5 min.
- `calidad_1h` (cada hora): muestras, faltantes, con observaciones, tardías y retraso máximo. Completitud = muestras / (muestras + faltantes).

## Instalación y operación

Desde el Mac: `herramientas/nodo.sh procesamiento` (corre las pruebas, copia la carpeta y ejecuta `instalar_procesamiento.sh` en la Pi). En la Pi, el instalador crea el depósito, el token (`/etc/puente/procesador.env`), el entorno en `/opt/procesador`, el temporizador `procesador.timer` y las tareas, y hace una primera corrida sobre las últimas 24 h.

Comprobaciones en la Pi:

```bash
systemctl list-timers procesador.timer
journalctl -u procesador -n 20 --no-pager
influx task list
influx query 'from(bucket:"cuarto_procesado") |> range(start:-2h) |> filter(fn:(r)=> r._measurement=="telemetria_5m" and r._field=="t") |> keep(columns:["_time","_value"])'
```

Reprocesar un rango (por ejemplo, tras cambiar una regla) y rehacer los agregados: en la Pi, `bash tareas/rehacer.sh <desde> <hasta>` tras
`sudo -u puente /opt/procesador/.venv/bin/python /opt/procesador/procesador.py --influx --desde 2026-10-31T00:00:00 --hasta 2026-11-04T00:00:00 --config /etc/puente/procesador.env`. La escritura es idempotente: las mismas marcas de tiempo se sobrescriben.

## Análisis fuera de línea (`borde/procesamiento/analisis.py`)

Descriptiva por variable, correlaciones de Pearson, descriptiva por franja de día (06:00 a 18:00) y noche, perfil por hora del día, y una regresión lineal por mínimos cuadrados que predice la temperatura (o la humedad) a 30 y 60 min con los valores de los últimos 30 min, la otra variable y la hora del día, evaluada por división temporal y comparada con la predicción ingenua de persistencia. Sirve para el informe; no forma parte de la plataforma.
