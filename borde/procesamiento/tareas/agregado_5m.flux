// Agregados de 5 min sobre la telemetría limpia. Corre cada 5 min con 2 min de margen para que el
// procesador haya escrito; relee 3 h 20 min, el horizonte de la cola del nodo, para incorporar muestras entregadas tarde (la
// escritura en InfluxDB es idempotente por serie y marca de tiempo).
//
// Cada grupo de campos se lee con su propio from(): en Flux una misma variable no puede usarse con
// _value de tipos distintos (flotante, entero, booleano) en pipelines diferentes.
option task = {name: "agregado_5m", every: 5m, offset: 2m}

deposito = "cuarto_procesado"
ventana = 5m

leer = (campos) =>
    from(bucket: deposito)
        |> range(start: -3h20m)
        |> filter(fn: (r) => r._measurement == "telemetria_limpia")
        |> filter(fn: (r) => contains(value: r._field, set: campos))

escribir = (tablas=<-) =>
    tablas
        |> set(key: "_measurement", value: "telemetria_5m")
        |> to(bucket: deposito)

// medias de las variables continuas
leer(campos: ["t", "hr", "pr", "i", "potencia_va"])
    |> aggregateWindow(every: ventana, fn: mean, createEmpty: false)
    |> escribir()

// extremos
leer(campos: ["t", "hr", "i"])
    |> aggregateWindow(every: ventana, fn: max, createEmpty: false)
    |> map(fn: (r) => ({r with _field: r._field + "_max"}))
    |> escribir()

leer(campos: ["t", "hr"])
    |> aggregateWindow(every: ventana, fn: min, createEmpty: false)
    |> map(fn: (r) => ({r with _field: r._field + "_min"}))
    |> escribir()

// fracción del tiempo con la puerta abierta y con agua (0 a 1)
leer(campos: ["puerta", "agua_f"])
    |> map(fn: (r) => ({r with _value: if r._value then 1.0 else 0.0}))
    |> aggregateWindow(every: ventana, fn: mean, createEmpty: false)
    |> map(fn: (r) => ({r with _field: r._field + "_fraccion"}))
    |> escribir()

// energía aparente acumulada en la ventana (VA·h)
leer(campos: ["energia_vah"])
    |> aggregateWindow(every: ventana, fn: sum, createEmpty: false)
    |> escribir()

// número de muestras
leer(campos: ["seq"])
    |> aggregateWindow(every: ventana, fn: count, createEmpty: false)
    |> map(fn: (r) => ({r with _field: "muestras"}))
    |> escribir()
