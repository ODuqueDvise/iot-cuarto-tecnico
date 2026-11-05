// Resumen horario a partir de los agregados de 5 min: media, extremos, fracciones y energía.
// Un from() por grupo de campos (ver agregado_5m.flux).
option task = {name: "resumen_1h", every: 1h, offset: 8m}

deposito = "cuarto_procesado"

leer = (campos) =>
    from(bucket: deposito)
        |> range(start: -3h)
        |> filter(fn: (r) => r._measurement == "telemetria_5m")
        |> filter(fn: (r) => contains(value: r._field, set: campos))

escribir = (tablas=<-) =>
    tablas
        |> set(key: "_measurement", value: "telemetria_1h")
        |> to(bucket: deposito)

leer(campos: ["t", "hr", "pr", "i", "potencia_va", "puerta_fraccion", "agua_f_fraccion"])
    |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
    |> escribir()

leer(campos: ["t_max", "hr_max", "i_max"])
    |> aggregateWindow(every: 1h, fn: max, createEmpty: false)
    |> escribir()

leer(campos: ["t_min", "hr_min"])
    |> aggregateWindow(every: 1h, fn: min, createEmpty: false)
    |> escribir()

leer(campos: ["energia_vah"])
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> escribir()

leer(campos: ["muestras"])
    |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
    |> escribir()
