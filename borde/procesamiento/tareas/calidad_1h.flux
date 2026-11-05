// Calidad del dato por hora: muestras recibidas, faltantes, con observaciones, tardías y retraso máximo.
// Con periodo de 30 s se esperan 120 muestras por hora; la completitud es muestras / (muestras + faltantes).
// Un from() por campo (ver agregado_5m.flux).
option task = {name: "calidad_1h", every: 1h, offset: 6m}

deposito = "cuarto_procesado"

leer = (campo) =>
    from(bucket: deposito)
        |> range(start: -3h)
        |> filter(fn: (r) => r._measurement == "telemetria_limpia" and r._field == campo)

escribir = (tablas=<-) =>
    tablas
        |> set(key: "_measurement", value: "calidad_1h")
        |> to(bucket: deposito)

leer(campo: "seq")
    |> aggregateWindow(every: 1h, fn: count, createEmpty: false)
    |> map(fn: (r) => ({r with _field: "muestras"}))
    |> escribir()

leer(campo: "faltantes")
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> escribir()

leer(campo: "calidad")
    |> map(fn: (r) => ({r with _value: if r._value > 0 then 1 else 0}))
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> map(fn: (r) => ({r with _field: "con_observaciones"}))
    |> escribir()

leer(campo: "calidad")
    |> map(fn: (r) => ({r with _value: if r._value % 64 >= 32 then 1 else 0}))
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> map(fn: (r) => ({r with _field: "tardias"}))
    |> escribir()

leer(campo: "retraso_ms")
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> map(fn: (r) => ({r with _field: "retraso_ms_max"}))
    |> escribir()
