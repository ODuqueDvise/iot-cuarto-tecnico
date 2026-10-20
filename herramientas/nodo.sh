#!/bin/bash
# Atajo para todo el trabajo con el nodo ESP32. Se ejecuta en el Mac, desde cualquier carpeta.
#
#   nodo.sh                      compila, carga y abre el monitor (lo normal después de un cambio)
#   nodo.sh compilar             solo compila
#   nodo.sh cargar               compila y carga, sin monitor
#   nodo.sh monitor              abre el monitor serie (salir con Ctrl+])
#   nodo.sh capturar [N]         guarda los registros en datos/captura_<fecha>.csv; con N, se detiene en N
#   nodo.sh oficial              prueba oficial: 360 registros en datos/oficial_<fecha>.csv
#   nodo.sh modos                muestra el modo de cada sensor y el periodo
#   nodo.sh modo <sensor> <modo> sensor: temperatura, corriente, puerta, agua o todos
#                                modo: real, simulado o ausente  (ejemplo: nodo.sh modo temperatura real)
#   nodo.sh contacto <tipo>      contacto de puerta: normal (cierra con el imán) o invertido (abre con el imán)
#   nodo.sh pruebas              pruebas de los cálculos en el computador
#   nodo.sh borde                comprueba que el borde (Raspberry Pi) responda: red, MQTT y hora
#   nodo.sh puente               prueba, instala y reinicia en la Pi el puente MQTT a InfluxDB del repositorio
#   nodo.sh registrador          prueba, instala y reinicia en la Pi el registrador CSV del borde
#   nodo.sh panel                prueba las consultas e instala en Grafana el tablero del nodo sensor
#   nodo.sh corte [segundos]     detiene Mosquitto en la Pi durante N s (120 por defecto) para probar la cola
#   nodo.sh ensayo [min] [s]     ensayo N-07 completo: 360 registros, corte de Mosquitto de s segundos (120) a los
#                                min minutos (90), y al final trae el CSV del borde, valida y compara
#   nodo.sh traer [AAAAMMDD]     copia del borde los CSV de ese día (hoy por defecto) a datos/borde/
#   nodo.sh validar <csv> [...]  valida un archivo de registros (ver validar_archivo.py --help)
#
# Variables opcionales: PUERTO=/dev/cu.xxx si hay más de un puerto serie; IDF_EXPORT=<ruta a export.sh>
# si ESP-IDF está en un lugar que el guion no encuentra; BORDE_USUARIO si el usuario de la Pi no es
# el de la bitácora (odukec).

set -euo pipefail

HERRAMIENTAS="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERRAMIENTAS/.." && pwd)"
NODO="$REPO/nodo"
DATOS="$REPO/datos"

fallar() { echo "ERROR: $*" >&2; exit 1; }
# sed -i distinto en macOS (BSD) y Linux (GNU)
sed_i() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }
aviso()  { echo "==> $*"; }

# ---------- ESP-IDF ----------
activar_idf() {
    if command -v idf.py >/dev/null 2>&1; then
        return 0
    fi
    local candidato=""
    if [ -n "${IDF_EXPORT:-}" ]; then
        candidato="$IDF_EXPORT"
    elif [ -n "${IDF_PATH:-}" ] && [ -f "$IDF_PATH/export.sh" ]; then
        candidato="$IDF_PATH/export.sh"
    else
        # Ubicaciones habituales: instalación manual, extensión de VS Code e instalador EIM.
        for c in "$HOME"/.espressif/tools/activate_idf_v5.5*.sh \
                 "$HOME"/esp/v5.5*/esp-idf/export.sh \
                 "$HOME"/.espressif/v5.5*/esp-idf/export.sh \
                 "$HOME"/esp/esp-idf/export.sh \
                 "$HOME"/esp/*/esp-idf/export.sh \
                 "$HOME"/.espressif/v*/esp-idf/export.sh \
                 "$HOME"/.espressif/tools/activate_idf_v*.sh; do
            if [ -f "$c" ]; then candidato="$c"; break; fi
        done
        if [ -z "$candidato" ]; then
            aviso "buscando ESP-IDF en la carpeta personal (una sola vez por terminal)"
            candidato="$(find "$HOME" -maxdepth 5 -name export.sh -path '*esp-idf/export.sh' 2>/dev/null | head -1 || true)"
        fi
    fi
    [ -n "$candidato" ] || fallar "no encontré ESP-IDF. Ejecuta: IDF_EXPORT=<ruta a esp-idf/export.sh> $0 $*"
    aviso "activando ESP-IDF: $candidato"
    # export.sh no está escrito para set -eu; se relaja solo mientras se carga
    set +eu
    # shellcheck disable=SC1090
    source "$candidato" >/tmp/nodo_idf_activacion.log 2>&1
    local r=$?
    set -eu
    [ $r -eq 0 ] || { cat /tmp/nodo_idf_activacion.log >&2; fallar "falló la activación de ESP-IDF con $candidato"; }
    command -v idf.py >/dev/null 2>&1 || fallar "ESP-IDF activado pero idf.py no aparece en el PATH"
}

# ---------- Puerto serie ----------
elegir_puerto() {
    if [ -n "${PUERTO:-}" ]; then
        echo "$PUERTO"
        return
    fi
    local lista=()
    for p in /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.usbmodem*; do
        [ -e "$p" ] && lista+=("$p")
    done
    # Con el controlador de Silicon Labs instalado, macOS publica el mismo CP210x dos veces:
    # /dev/cu.usbserial-XXXX y /dev/cu.SLAB_USBtoUART. Este último solo se usa si no hay otro.
    if [ "${#lista[@]}" -eq 0 ]; then
        for p in /dev/cu.SLAB_USBtoUART*; do
            [ -e "$p" ] && lista+=("$p")
        done
    fi
    if [ "${#lista[@]}" -eq 0 ]; then
        fallar "no hay ningún ESP32 conectado por USB (revisa el cable: algunos solo cargan y no transmiten datos)"
    fi
    if [ "${#lista[@]}" -gt 1 ]; then
        echo "Hay varios puertos: ${lista[*]}" >&2
        fallar "elige uno con PUERTO=<puerto> $0 ..."
    fi
    echo "${lista[0]}"
}

# El monitor de idf.py o una captura abiertos en otra terminal bloquean el puerto y la carga falla.
revisar_puerto_libre() {
    local puerto="$1" pids
    pids="$(lsof -t "$puerto" 2>/dev/null || true)"
    [ -z "$pids" ] && return 0
    echo "El puerto $puerto está ocupado por:" >&2
    for p in $pids; do ps -o pid=,command= -p "$p" >&2 || true; done
    fallar "cierra ese monitor o esa captura (Ctrl+] o Ctrl+C en su terminal) y vuelve a intentar"
}

# ---------- Comprobaciones previas a compilar ----------
revisar_secretos() {
    local faltan=()
    [ -f "$NODO/main/secretos.h" ] || faltan+=("nodo/main/secretos.h (copiar de secretos.h.ejemplo)")
    for f in ca.crt nodo.crt nodo.key; do
        [ -f "$NODO/main/certs/$f" ] || faltan+=("nodo/main/certs/$f")
    done
    if [ "${#faltan[@]}" -gt 0 ]; then
        printf 'Faltan archivos que no están en el repositorio:\n' >&2
        printf '  %s\n' "${faltan[@]}" >&2
        fallar "ver docs/03_nodo.md, sección Configurar"
    fi
}

compilar() {
    activar_idf
    revisar_secretos
    cd "$NODO"
    if [ ! -f sdkconfig ]; then
        aviso "sin sdkconfig: se genera desde sdkconfig.defaults para el ESP32"
        idf.py set-target esp32
    fi
    idf.py build
}

# ---------- Modos de los sensores ----------
nombre_kconfig() {
    case "$1" in
        temperatura|sht31) echo SHT31 ;;
        corriente)         echo CORRIENTE ;;
        puerta)            echo PUERTA ;;
        agua)              echo AGUA ;;
        *) fallar "sensor desconocido: $1 (temperatura, corriente, puerta, agua o todos)" ;;
    esac
}

fijar_modo() {
    local sensor="$1" modo
    case "$2" in
        real) modo=REAL ;; simulado) modo=SIMULADO ;; ausente) modo=AUSENTE ;;
        *) fallar "modo desconocido: $2 (real, simulado o ausente)" ;;
    esac
    local k
    k="$(nombre_kconfig "$sensor")"
    local archivo="$NODO/sdkconfig"
    for m in REAL SIMULADO AUSENTE; do
        # borra cualquier forma previa de la opción y escribe la nueva al final
        sed_i -e "/^CONFIG_NODO_${k}_${m}=/d" -e "/^# CONFIG_NODO_${k}_${m} is not set/d" "$archivo"
        if [ "$m" = "$modo" ]; then
            echo "CONFIG_NODO_${k}_${m}=y" >> "$archivo"
        else
            echo "# CONFIG_NODO_${k}_${m} is not set" >> "$archivo"
        fi
    done
    aviso "$sensor: $2"
}

modo() {
    [ $# -eq 2 ] || fallar "uso: $0 modo <temperatura|corriente|puerta|agua|todos> <real|simulado|ausente>"
    [ "$1" = "todos" ] || nombre_kconfig "$1" >/dev/null
    case "$2" in real|simulado|ausente) ;; *) fallar "modo desconocido: $2 (real, simulado o ausente)" ;; esac
    activar_idf
    cd "$NODO"
    [ -f sdkconfig ] || idf.py set-target esp32
    if [ "$1" = "todos" ]; then
        for s in temperatura corriente puerta agua; do fijar_modo "$s" "$2"; done
    else
        fijar_modo "$1" "$2"
    fi
    idf.py reconfigure >/tmp/nodo_reconfigurar.log 2>&1 || { cat /tmp/nodo_reconfigurar.log >&2; fallar "idf.py reconfigure falló"; }
    modos
    aviso "para que el cambio llegue al nodo: $0"
}

modos() {
    local archivo="$NODO/sdkconfig"
    [ -f "$archivo" ] || fallar "todavía no hay sdkconfig; ejecuta primero: $0 compilar"
    local periodo
    periodo="$(sed -n 's/^CONFIG_NODO_PERIODO_S=//p' "$archivo")"
    echo "Periodo de muestreo: ${periodo:-?} s"
    for s in temperatura corriente puerta agua; do
        local k m
        k="$(nombre_kconfig "$s")"
        m="$(grep -oE "^CONFIG_NODO_${k}_(REAL|SIMULADO|AUSENTE)=y" "$archivo" | sed -E "s/^CONFIG_NODO_${k}_//; s/=y//" || true)"
        printf '  %-12s %s\n' "$s" "$(echo "${m:-?}" | tr '[:upper:]' '[:lower:]')"
    done
    if grep -q "^CONFIG_NODO_PUERTA_REAL=y" "$archivo"; then
        if grep -q "^CONFIG_NODO_PUERTA_INVERTIDA=y" "$archivo"; then
            echo "  contacto de puerta: invertido (abre con el imán; un cable cortado se lee como cerrada)"
        else
            echo "  contacto de puerta: normal (cierra con el imán)"
        fi
    fi
}

contacto() {
    case "${1:-}" in normal|invertido) ;; *) fallar "uso: $0 contacto <normal|invertido>" ;; esac
    activar_idf
    cd "$NODO"
    [ -f sdkconfig ] || idf.py set-target esp32
    sed_i -e "/^CONFIG_NODO_PUERTA_INVERTIDA=/d" -e "/^# CONFIG_NODO_PUERTA_INVERTIDA is not set/d" sdkconfig
    if [ "$1" = "invertido" ]; then
        echo "CONFIG_NODO_PUERTA_INVERTIDA=y" >> sdkconfig
    else
        echo "# CONFIG_NODO_PUERTA_INVERTIDA is not set" >> sdkconfig
    fi
    idf.py reconfigure >/tmp/nodo_reconfigurar.log 2>&1 || { cat /tmp/nodo_reconfigurar.log >&2; fallar "idf.py reconfigure falló"; }
    modos
    aviso "para que el cambio llegue al nodo: $0"
}

# ---------- Borde ----------
# Toma la dirección del borde de secretos.h, la misma que usa el nodo.
host_borde() {
    local secretos="$NODO/main/secretos.h" host
    [ -f "$secretos" ] || fallar "falta nodo/main/secretos.h"
    host="$(sed -n 's/.*MQTT_URI.*mqtts:\/\/\([^:"]*\).*/\1/p' "$secretos" | head -1)"
    [ -n "$host" ] || fallar "no encontré la dirección del borde en MQTT_URI de secretos.h"
    echo "$host"
}

revisar_borde() {
    local host
    host="$(host_borde)"
    local ok=1
    if ping -c 2 -t 3 "$host" >/dev/null 2>&1 || ping -c 2 -w 3 "$host" >/dev/null 2>&1; then
        echo "  borde $host: responde"
    else
        echo "  borde $host: NO responde (¿apagado o con otra IP?)"; ok=0
    fi
    if [ $ok -eq 1 ]; then
        if nc -z -G 3 "$host" 8883 >/dev/null 2>&1 || nc -z -w 3 "$host" 8883 >/dev/null 2>&1; then
            echo "  MQTT (8883): abierto"
        else
            echo "  MQTT (8883): cerrado (¿Mosquitto detenido?)"; ok=0
        fi
        if command -v sntp >/dev/null 2>&1; then
            if sntp "$host" >/dev/null 2>&1; then echo "  hora (NTP): responde"; else echo "  hora (NTP): NO responde (¿chrony detenido?)"; ok=0; fi
        fi
    fi
    [ $ok -eq 1 ] || return 1
}

# Prueba el puente del repositorio en la Pi con su propio entorno y, si pasa, lo instala y lo reinicia.
actualizar_puente() {
    local host usuario="${BORDE_USUARIO:-odukec}"
    host="$(host_borde)"
    local origen="$REPO/borde/puente"
    aviso "copiando el puente a $usuario@$host"
    ssh "$usuario@$host" 'rm -rf /tmp/puente_nuevo && mkdir -p /tmp/puente_nuevo'
    scp -q "$origen/puente.py" "$origen/prueba_puente.py" "$usuario@$host:/tmp/puente_nuevo/"
    aviso "probando, instalando y reiniciando (sudo puede pedir la contraseña de la Pi)"
    ssh -t "$usuario@$host" 'set -e
        cd /tmp/puente_nuevo
        /opt/puente/.venv/bin/python prueba_puente.py
        sudo install -o puente -g puente -m 644 puente.py /opt/puente/puente.py
        sudo systemctl restart puente
        sleep 4
        echo "servicio puente: $(systemctl is-active puente)"
        sudo journalctl -u puente -n 8 --no-pager'
}

# Igual que el puente: prueba en la Pi con el entorno del puente y, si pasa, instala y reinicia.
actualizar_registrador() {
    local host usuario="${BORDE_USUARIO:-odukec}"
    host="$(host_borde)"
    local origen="$REPO/borde/registrador"
    aviso "copiando el registrador a $usuario@$host"
    ssh "$usuario@$host" 'rm -rf /tmp/registrador_nuevo && mkdir -p /tmp/registrador_nuevo'
    scp -q "$origen/registrador_csv.py" "$origen/prueba_registrador.py" "$origen/registrador.service" \
        "$usuario@$host:/tmp/registrador_nuevo/"
    aviso "probando, instalando y reiniciando (sudo puede pedir la contraseña de la Pi)"
    ssh -t "$usuario@$host" 'set -e
        cd /tmp/registrador_nuevo
        /opt/puente/.venv/bin/python prueba_registrador.py
        sudo install -d -m 755 /opt/registrador
        sudo install -m 644 registrador_csv.py /opt/registrador/registrador_csv.py
        sudo install -m 644 registrador.service /etc/systemd/system/registrador.service
        sudo systemctl daemon-reload
        sudo systemctl enable registrador >/dev/null 2>&1
        sudo systemctl restart registrador
        sleep 5
        echo "servicio registrador: $(systemctl is-active registrador)"
        sudo journalctl -u registrador -n 6 --no-pager
        ultimo="$(ls -t /var/lib/registrador/*.csv 2>/dev/null | head -1)"
        if [ -n "$ultimo" ]; then echo "== $ultimo"; tail -3 "$ultimo"; else echo "todavía no hay archivo: llega con la próxima muestra con hora"; fi'
}

# Prueba cada consulta del tablero contra InfluxDB en la Pi y, si todas corren, lo instala en Grafana.
actualizar_panel() {
    local host usuario="${BORDE_USUARIO:-odukec}"
    host="$(host_borde)"
    local origen="$REPO/borde/grafana"
    aviso "copiando el tablero a $usuario@$host"
    ssh "$usuario@$host" 'rm -rf /tmp/panel_nuevo && mkdir -p /tmp/panel_nuevo'
    scp -q "$origen/nodo_sensor.json" "$origen/tablero.yaml" "$origen/probar_consultas.py" "$usuario@$host:/tmp/panel_nuevo/"
    aviso "probando las consultas, instalando y reiniciando Grafana (sudo puede pedir la contraseña)"
    ssh -t "$usuario@$host" 'set -e
        cd /tmp/panel_nuevo
        python3 probar_consultas.py nodo_sensor.json
        sudo install -d -o grafana -g grafana /var/lib/grafana/dashboards/cuarto
        sudo install -o grafana -g grafana -m 644 nodo_sensor.json /var/lib/grafana/dashboards/cuarto/nodo_sensor.json
        sudo install -m 644 tablero.yaml /etc/grafana/provisioning/dashboards/cuarto.yaml
        sudo systemctl restart grafana-server
        echo "esperando a Grafana..."
        for i in $(seq 1 30); do curl -sf http://localhost:3000/api/health >/dev/null && break; sleep 2; done
        echo "servicio grafana-server: $(systemctl is-active grafana-server)"
        sudo journalctl -u grafana-server --since "-2 min" --no-pager | grep -iE "provisioning.dashboard|dashboard.*(error|fail)" | tail -5 || true'
    echo "Tablero: http://$host:3000/d/nodo-sensor"
}

# Corte controlado del intermediario: el nodo debe retener las muestras y enviarlas al volver.
corte() {
    local host usuario="${BORDE_USUARIO:-odukec}" s="${1:-120}"
    host="$(host_borde)"
    aviso "deteniendo Mosquitto en $host durante $s s ($(date +%H:%M:%S))"
    ssh -t "$usuario@$host" "sudo systemctl stop mosquitto && sleep $s && sudo systemctl start mosquitto && echo \"Mosquitto: \$(systemctl is-active mosquitto)\""
    aviso "Mosquitto de vuelta ($(date +%H:%M:%S)); el nodo debe vaciar su cola en los siguientes segundos"
}

nodo_id() {
    sed -n 's/.*NODO_ID[^"]*"\([^"]*\)".*/\1/p' "$NODO/main/secretos.h" | head -1
}

# Ensayo N-07 de punta a punta, sin intervención: el corte lo programa la propia Pi con un temporizador de
# systemd, así que sudo se pide una sola vez al comienzo y el Mac no necesita otra terminal.
ensayo() {
    local minutos="${1:-90}" segundos="${2:-120}" host usuario="${BORDE_USUARIO:-odukec}"
    host="$(host_borde)"
    local nodo
    nodo="$(nodo_id)"
    # Todo lo que puede fallar se revisa antes de programar el corte en la Pi.
    activar_idf
    local puerto
    puerto="$(elegir_puerto)"
    revisar_puerto_libre "$puerto"
    echo "Borde:"
    revisar_borde || fallar "el borde no está listo"
    echo
    modos
    echo
    local unidad
    unidad="corte-ensayo-$(date +%Y%m%d%H%M%S)"
    aviso "programando en la Pi un corte de Mosquitto de $segundos s dentro de $minutos min (sudo puede pedir la contraseña)"
    ssh -t "$usuario@$host" "sudo systemd-run --quiet --unit=$unidad --on-active=${minutos}min /bin/sh -c 'systemctl stop mosquitto; sleep $segundos; systemctl start mosquitto'"
    aviso "corte previsto hacia las $(date -v+${minutos}M +%H:%M 2>/dev/null || date -d "+$minutos min" +%H:%M); la captura termina sola en unas 3 h"

    # Ctrl+C detiene la captura pero no el guion: así se cancela el corte pendiente y se valida lo capturado.
    trap ':' INT
    capturar 360 ensayo || true
    trap - INT

    if [ "$(ssh "$usuario@$host" "systemctl is-active $unidad.timer" 2>/dev/null)" = "active" ]; then
        aviso "la captura terminó antes del corte: se cancela el corte programado"
        ssh -t "$usuario@$host" "sudo systemctl stop $unidad.timer" || true
    fi

    echo
    traer "$(date +%Y%m%d)" || aviso "no se pudo traer el CSV del borde"
    local borde="$DATOS/borde/${nodo}_$(date +%Y%m%d).csv"
    echo
    if [ -f "$borde" ]; then
        python3 "$HERRAMIENTAS/validar_archivo.py" "$ULTIMA_CAPTURA" --muestras 360 --comparar "$borde" || true
    else
        python3 "$HERRAMIENTAS/validar_archivo.py" "$ULTIMA_CAPTURA" --muestras 360 || true
    fi
    echo
    echo "En el resultado se esperan unas 4 filas con 'sin MQTT al registrar' (el corte) y ninguna falla."
    echo "Panel: http://$host:3000/d/nodo-sensor (muestras por hora sin hueco a la hora del corte)."
}

traer() {
    local host usuario="${BORDE_USUARIO:-odukec}" fecha="${1:-$(date +%Y%m%d)}"
    host="$(host_borde)"
    mkdir -p "$DATOS/borde"
    aviso "copiando /var/lib/registrador/*_$fecha.csv a $DATOS/borde/"
    scp "$usuario@$host:/var/lib/registrador/*_$fecha.csv" "$DATOS/borde/"
    ls -l "$DATOS/borde/"*"_$fecha.csv"
}

# ---------- Captura ----------
capturar() {
    local muestras="${1:-0}" prefijo="${2:-captura}"
    activar_idf   # trae el Python con pyserial
    local puerto
    puerto="$(elegir_puerto)"
    revisar_puerto_libre "$puerto"
    mkdir -p "$DATOS"
    local salida
    salida="$DATOS/${prefijo}_$(date +%Y%m%d_%H%M).csv"
    aviso "capturando $puerto en $salida"
    ULTIMA_CAPTURA="$salida"
    # caffeinate impide que el Mac entre en reposo mientras dura la captura (3 h en la prueba).
    local espera=""
    command -v caffeinate >/dev/null 2>&1 && espera="caffeinate -i"
    $espera python "$HERRAMIENTAS/capturar_serie.py" --puerto "$puerto" --salida "$salida" --muestras "$muestras"
}

# ---------- Principal ----------
orden="${1:-todo}"
[ $# -gt 0 ] && shift
case "$orden" in
    todo)
        compilar
        puerto="$(elegir_puerto)"
        revisar_puerto_libre "$puerto"
        idf.py -p "$puerto" flash monitor
        ;;
    compilar) compilar ;;
    cargar)
        compilar
        puerto="$(elegir_puerto)"
        revisar_puerto_libre "$puerto"
        idf.py -p "$puerto" flash
        ;;
    monitor)
        activar_idf
        cd "$NODO"
        puerto="$(elegir_puerto)"
        revisar_puerto_libre "$puerto"
        idf.py -p "$puerto" monitor
        ;;
    capturar) capturar "${1:-0}" captura ;;
    borde)
        revisar_borde || fallar "el borde no está listo"
        ;;
    puente) actualizar_puente ;;
    registrador) actualizar_registrador ;;
    panel) actualizar_panel ;;
    corte) corte "${1:-120}" ;;
    ensayo) ensayo "${1:-90}" "${2:-120}" ;;
    traer) traer "${1:-}" ;;
    validar)
        [ $# -ge 1 ] || fallar "uso: $0 validar <archivo.csv> [opciones de validar_archivo.py]"
        # Rutas relativas: valen desde la carpeta actual o, si ahí no existen, desde la del proyecto.
        if [ ! -e "$1" ] && [ -e "$REPO/$1" ]; then cd "$REPO"; fi
        python3 "$HERRAMIENTAS/validar_archivo.py" "$@"
        ;;
    oficial)
        echo "Borde:"
        revisar_borde || fallar "el borde no está listo; la prueba oficial necesita hora y MQTT desde el arranque del nodo"
        echo
        modos
        echo
        read -r -p "¿Todos los sensores de la prueba están en modo real? (s/n) " r
        [ "$r" = "s" ] || fallar "cambia los modos con: $0 modo <sensor> real"
        capturar 360 oficial
        echo
        extra=""
        python3 -c "import openpyxl" 2>/dev/null && extra="--xlsx"
        python3 "$HERRAMIENTAS/validar_archivo.py" "$ULTIMA_CAPTURA" --muestras 360 --oficial $extra || true
        ;;
    modos) modos ;;
    modo) modo "$@" ;;
    contacto) contacto "$@" ;;
    pruebas)
        cd "$NODO/pruebas"
        cc -std=gnu11 -I../main prueba_calculos.c ../main/calculos.c -lm -o /tmp/prueba_calculos_nodo
        /tmp/prueba_calculos_nodo
        ;;
    ayuda|-h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) fallar "orden desconocida: $orden (ver: $0 ayuda)" ;;
esac
