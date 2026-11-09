# 6. Visualización, análisis y alertas (Actividad 5)

## Tablero "Operación del cuarto técnico" (`/d/operacion`)

Generado por `borde/grafana/generar_operacion.py` (no se edita a mano el JSON). Se lee de arriba abajo, de lo urgente a
lo analítico; cada panel trae en su descripción (icono "i") la pregunta que responde y qué hacer.

| Franja | Fuente | Rango | Para qué |
|---|---|---|---|
| Ahora | crudo `cuarto` | últimos 15 min, fijo en la consulta | ¿Hay que actuar ya? Valores con color por umbral, nodo en línea, alertas |
| Últimas 24 h | crudo `cuarto` | 24 h, fijo en el panel | ¿Cómo viene el día? Series con zonas fuera de norma y eventos marcados |
| Análisis | procesado `cuarto_procesado` | el del selector (7 días por defecto) | ¿Cómo se comporta el cuarto? Análisis básico sobre datos limpios |

El tiempo real sale del crudo porque el procesado se actualiza cada 10 min; el análisis sale del procesado porque ya no
tiene arranques, fallos ni duplicados.

Umbrales: recomendación ASHRAE para salas de equipos de TI, temperatura de 18 a 27 °C, HR hasta 60 %, punto de rocío
hasta 15 °C. En la línea base (31 oct. a 4 nov.) la temperatura estuvo entre 21,4 y 24,6 °C; la HR llegó a 59,8 % y el
punto de rocío a 14,8 °C: la humedad es la variable con menos margen.

Análisis (técnicas de la unidad 3): descriptiva (media, mediana, desviación, mínimo, máximo, rango; la moda se omite en
variables continuas), completitud del dato, porcentaje del tiempo dentro de norma, matriz de correlación de Pearson,
perfil por hora del día (hora local, UTC menos 5), histograma de temperatura, anomalías por banda de media ± 3
desviaciones sobre los agregados de 5 min, y totales por día de puerta y energía.

Privacidad: las aperturas de la puerta se muestran como totales por día; la hora de cada ingreso puede identificar a
quien entró (Ley 1581 de 2012).

## Alertas por correo (`alertas.yaml`)

| Regla | Condición | Severidad |
|---|---|---|
| Agua en el piso | `agua` en todas las muestras de los últimos 65 s (dos seguidas) | crítica |
| Nodo sin datos | más de 90 s desde la última muestra, o ninguna en 1 h | crítica |
| Temperatura alta | media de 5 min sobre 27 °C durante 15 min | alta |
| Humedad alta | media de 5 min sobre 60 % durante 15 min | alta |
| Punto de rocío alto | media de 5 min sobre 15 °C durante 15 min | alta |
| Puerta abierta | abierta en todas las muestras de 10 min | media |

Grafana evalúa cada 30 s. Dos políticas al mismo buzón, separadas por la etiqueta `severidad`:

| Severidad | Punto de contacto | Espera | Repite si persiste | Aviso al resolver |
|---|---|---|---|---|
| crítica (agua, nodo) | Correo urgente | 10 s | cada 4 h | sí |
| alta y media (ambiente, puerta) | Correo informativo | 1 min | cada 24 h | no |

Por qué: con una sola política (repetir cada 4 h y avisar al resolver) llegaron 16 correos de humedad y punto de rocío
entre el 6 y el 8 de noviembre. No eran oscilaciones: la HR estuvo sobre 60 % de forma continua de 00:30 a 07:39 el
8 de noviembre, y cada episodio generó dos o tres correos. Esa condición pide una decisión de mantenimiento que se toma
una vez, no una respuesta de madrugada; un correo por episodio basta. Las tres reglas ambientales exigen además 15 min
sostenidos (`for`) y siguen activas 30 min después de bajar del umbral (`keep_firing_for`): el 7 de noviembre la HR
bajó de 60 % a las 09:17 y volvió a subir a las 09:29, lo que generó dos episodios con sus correos.

Historial de la regla de humedad (estado Alerting, hora local): 6 nov. 19:32 a 20:26; 7 nov. 00:56 a 09:17 y 09:29 a
09:50; 8 nov. 00:30 a 07:38. Punto de rocío: 6 nov. 19:32 a 7 nov. 03:12; 7 nov. 19:03 a 19:14.
Las reglas están aprovisionadas por archivo: no se editan en la interfaz.

Correo: `/etc/grafana/correo.env` en la Pi (600, root), cargado por el drop-in `correo.conf`; modelo en
`correo.env.ejemplo`. La contraseña nunca entra al repositorio ni se imprime.

## Memoria

Grafana 13 en la Pi de 1 GB pasó de 356 a 452 MB en 85 s con el tablero abierto (8 de noviembre). Medidas: el
histograma se calcula en InfluxDB (40 filas en vez de 20.000 muestras), el refresco del tablero es de 1 min, y
`memoria.conf` fija `GOMEMLIMIT=300MiB` para que el recolector de Go libere antes del límite físico. Cada sesión SSH
desde Warp carga además su servidor remoto (`oz`, unos 80 MB) mientras dura.

## Instalación

Desde el Mac: `herramientas/nodo.sh operacion`. Genera los archivos, los copia a la Pi, prueba cada consulta del tablero
y de las alertas contra InfluxDB (30 min y luego 7 días para medir tiempos), instala el tablero y, si existe
`correo.env`, el correo y las alertas; reinicia Grafana y muestra los errores del registro.

Prueba del correo: Alertas, Puntos de contacto, "Correo del cuarto técnico", Probar.
