/* Nodo del cuarto técnico. Etapa 2: nodo sensor y adquisición de datos (Actividad 2).
 *
 * - Wi-Fi en modo estación, hora por SNTP desde el borde, MQTT 5.0 sobre TLS con certificado de
 *   cliente y mensaje de última voluntad (igual que la etapa 1).
 * - Muestreo sobre una cuadrícula absoluta: una muestra en cada múltiplo de CONFIG_NODO_PERIODO_S
 *   del reloj sincronizado, sin deriva acumulada.
 * - seq avanza en cada muestra tomada, haya o no conexión, así que una pérdida deja un hueco visible.
 * - Cada muestra sale por dos canales independientes:
 *   1. Una línea CSV por el puerto serie, que empieza por "REG," (la captura en el Mac la guarda).
 *   2. Un mensaje JSON por MQTT. Se encola en la cola de salida del cliente, que lo retiene si no hay
 *      conexión y lo envía al reconectar.
 */
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "cJSON.h"
#include "sdkconfig.h"

#include "secretos.h"
#include "calculos.h"
#include "sensores.h"
#include "led.h"

static const char *TAG = "nodo";

/* Certificados embebidos por EMBED_TXTFILES (terminados en cero). */
extern const uint8_t ca_crt_start[]   asm("_binary_ca_crt_start");
extern const uint8_t nodo_crt_start[] asm("_binary_nodo_crt_start");
extern const uint8_t nodo_key_start[] asm("_binary_nodo_key_start");

#define BIT_WIFI_OK BIT0
static EventGroupHandle_t eventos;
static esp_mqtt_client_handle_t cliente;
static volatile bool mqtt_conectado = false;

static char tema_telemetria[48];
static char tema_estado[48];
static char tema_comandos[48];

/* Columnas de la línea serie; el mismo orden usa la captura del Mac. */
#define CABECERA_CSV "seq,ts_epoch,ts_local_iso,retraso_ms,t_c,hr_pct,punto_rocio_c,i_media_a,i_max_a," \
                     "puerta,puerta_aperturas,agua,agua_eventos,estado_sensores,origen"

/* Cualquier fecha posterior a noviembre de 2023 se toma como hora válida. */
#define HORA_MINIMA_VALIDA 1700000000LL

/* ---------- Wi-Fi ---------- */
static void manejador_wifi(void *arg, esp_event_base_t base, int32_t id, void *datos)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(eventos, BIT_WIFI_OK);
        ESP_LOGW(TAG, "Wi-Fi desconectado, reintentando");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = datos;
        ESP_LOGI(TAG, "IP obtenida: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(eventos, BIT_WIFI_OK);
    }
}

static void iniciar_wifi(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &manejador_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &manejador_wifi, NULL));

    wifi_config_t wc = { 0 };
    strncpy((char *) wc.sta.ssid, WIFI_SSID, sizeof(wc.sta.ssid) - 1);
    strncpy((char *) wc.sta.password, WIFI_CLAVE, sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_MIN_MODEM));   /* modem-sleep entre transmisiones */
    ESP_ERROR_CHECK(esp_wifi_start());
}

/* ---------- Hora ---------- */
static void sincronizar_hora(void)
{
    /* Hora de Colombia, sin horario de verano. Solo afecta la columna ts_local_iso. */
    setenv("TZ", "<-05>5", 1);
    tzset();

    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG(SNTP_SERVIDOR);
    ESP_ERROR_CHECK(esp_netif_sntp_init(&cfg));
    if (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(15000)) == ESP_OK) {
        ESP_LOGI(TAG, "hora sincronizada con el borde: %lld", (long long) time(NULL));
    } else {
        ESP_LOGW(TAG, "sin hora del borde todavía; las muestras se marcarán sin hora hasta sincronizar");
    }
}

/* Reloj en microsegundos: el sincronizado si es válido; si no, el monótono desde el arranque. */
static int64_t reloj_us(bool *con_hora)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    if (tv.tv_sec > HORA_MINIMA_VALIDA) {
        *con_hora = true;
        return (int64_t) tv.tv_sec * 1000000LL + tv.tv_usec;
    }
    *con_hora = false;
    return esp_timer_get_time();
}

/* ---------- MQTT ---------- */
static void manejador_mqtt(void *arg, esp_event_base_t base, int32_t id, void *datos)
{
    esp_mqtt_event_handle_t ev = datos;
    switch ((esp_mqtt_event_id_t) id) {
    case MQTT_EVENT_CONNECTED:
        mqtt_conectado = true;
        ESP_LOGI(TAG, "MQTT conectado; mensajes en cola: %d bytes", esp_mqtt_client_get_outbox_size(cliente));
        esp_mqtt_client_publish(cliente, tema_estado, "en_linea", 0, 1, 1);
        esp_mqtt_client_subscribe(cliente, tema_comandos, 2);
        break;
    case MQTT_EVENT_DISCONNECTED:
        mqtt_conectado = false;
        ESP_LOGW(TAG, "MQTT desconectado");
        break;
    case MQTT_EVENT_DATA:
        ESP_LOGI(TAG, "comando en %.*s: %.*s", ev->topic_len, ev->topic, ev->data_len, ev->data);
        /* Etapa posterior: interpretar comandos (umbrales, horarios). Las reglas duras no se anulan desde aquí. */
        break;
    case MQTT_EVENT_ERROR:
        if (ev->error_handle->error_type == MQTT_ERROR_TYPE_TCP_TRANSPORT) {
            ESP_LOGE(TAG, "error de transporte o TLS: esp-tls 0x%x", ev->error_handle->esp_tls_last_esp_err);
        }
        break;
    default:
        break;
    }
}

static void iniciar_mqtt(void)
{
    snprintf(tema_telemetria, sizeof tema_telemetria, "cuarto/%s/telemetria", NODO_ID);
    snprintf(tema_estado,     sizeof tema_estado,     "cuarto/%s/estado",     NODO_ID);
    snprintf(tema_comandos,   sizeof tema_comandos,   "cuarto/%s/comandos",   NODO_ID);

    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = MQTT_URI,
        .broker.verification.certificate = (const char *) ca_crt_start,
        .broker.verification.common_name = MQTT_NOMBRE_COMUN,
        .credentials.client_id = NODO_ID,
        .credentials.authentication.certificate = (const char *) nodo_crt_start,
        .credentials.authentication.key = (const char *) nodo_key_start,
        .session.protocol_ver = MQTT_PROTOCOL_V_5,
        .session.keepalive = 10,
        .session.last_will = {
            .topic = tema_estado,
            .msg = "fuera_de_linea",
            .qos = 1,
            .retain = 1,
        },
        .network.reconnect_timeout_ms = 5000,
        .outbox.limit = CONFIG_NODO_COLA_SALIDA_KB * 1024,
    };
    cliente = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(cliente, ESP_EVENT_ANY_ID, manejador_mqtt, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(cliente));
}

/* ---------- Salida de cada muestra ---------- */

/* Escribe un número con `dec` decimales, o nada si es NAN (celda vacía en el CSV). */
static const char *num(char *buf, size_t n, float v, int dec)
{
    if (isnan(v)) {
        buf[0] = '\0';
    } else {
        snprintf(buf, n, "%.*f", dec, v);
    }
    return buf;
}

static const char *tres_estados(int8_t v)
{
    return v < 0 ? "" : (v ? "1" : "0");
}

static void imprimir_linea(const muestra_t *m, const char *origen)
{
    char iso[32] = "";
    if (m->ts > 0) {
        time_t t = (time_t) m->ts;
        struct tm tm;
        localtime_r(&t, &tm);
        strftime(iso, sizeof iso, "%Y-%m-%dT%H:%M:%S-05:00", &tm);
    }
    char t[12], hr[12], pr[12], im[12], ix[12];
    /* Una sola llamada a printf por línea, para que no se intercale con los mensajes de registro. */
    printf("REG,%lu,%lld,%s,%ld,%s,%s,%s,%s,%s,%s,%u,%s,%u,%lu,%s\n",
           (unsigned long) m->seq, (long long) m->ts, iso, (long) m->retraso_ms,
           num(t, sizeof t, m->t_c, 2), num(hr, sizeof hr, m->hr_pct, 2), num(pr, sizeof pr, m->pr_c, 2),
           num(im, sizeof im, m->i_media_a, 3), num(ix, sizeof ix, m->i_max_a, 3),
           tres_estados(m->puerta), (unsigned) m->puerta_aperturas,
           tres_estados(m->agua), (unsigned) m->agua_eventos,
           (unsigned long) m->estado, origen);
}

/* Agrega un número solo si existe: un campo ausente no llega al puente (que ignora lo que no conoce). */
static void agregar_num(cJSON *j, const char *clave, float v)
{
    if (!isnan(v)) {
        /* Redondeo en double: hacerlo en float deja residuos al imprimir (10.991000175...). */
        cJSON_AddNumberToObject(j, clave, round((double) v * 1000.0) / 1000.0);
    }
}

static void publicar(const muestra_t *m, const char *origen)
{
    cJSON *j = cJSON_CreateObject();
    cJSON_AddStringToObject(j, "nodo", NODO_ID);
    if (m->ts > 0) {
        cJSON_AddNumberToObject(j, "ts", (double) m->ts);
    }
    cJSON_AddNumberToObject(j, "seq", m->seq);
    cJSON_AddNumberToObject(j, "periodo", CONFIG_NODO_PERIODO_S);
    cJSON_AddNumberToObject(j, "retraso_ms", m->retraso_ms);
    agregar_num(j, "t", m->t_c);
    agregar_num(j, "hr", m->hr_pct);
    agregar_num(j, "pr", m->pr_c);
    agregar_num(j, "i", m->i_media_a);
    agregar_num(j, "i_max", m->i_max_a);
    if (m->puerta >= 0) {
        cJSON_AddBoolToObject(j, "puerta", m->puerta == 1);
        cJSON_AddNumberToObject(j, "puerta_n", m->puerta_aperturas);
    }
    if (m->agua >= 0) {
        cJSON_AddBoolToObject(j, "agua", m->agua == 1);
        cJSON_AddNumberToObject(j, "agua_n", m->agua_eventos);
    }
    cJSON_AddNumberToObject(j, "est", m->estado);
    cJSON_AddStringToObject(j, "origen", origen);

    char *s = cJSON_PrintUnformatted(j);
    if (s != NULL) {
        /* QoS 1. enqueue no bloquea: el mensaje queda en la cola de salida y la tarea MQTT lo envía
         * en cuanto haya conexión. */
        int id = esp_mqtt_client_enqueue(cliente, tema_telemetria, s, 0, 1, 0, true);
        if (id < 0) {
            ESP_LOGE(TAG, "muestra %lu no encolada (%s)", (unsigned long) m->seq,
                     id == -2 ? "cola de salida llena" : "error");
        } else {
            ESP_LOGD(TAG, "muestra %lu encolada (id %d, %d bytes)", (unsigned long) m->seq, id, (int) strlen(s));
        }
        cJSON_free(s);
    }
    cJSON_Delete(j);
}

/* ---------- LED de estado ---------- */
static led_red_t estado_red(void)
{
    if ((xEventGroupGetBits(eventos) & BIT_WIFI_OK) == 0) {
        return LED_SIN_WIFI;
    }
    bool con_hora;
    reloj_us(&con_hora);
    return (mqtt_conectado && con_hora) ? LED_EN_LINEA : LED_SIN_SERVIDOR;
}

/* ---------- Muestreo ---------- */
static void tarea_muestreo(void *arg)
{
    const int64_t periodo_us = (int64_t) CONFIG_NODO_PERIODO_S * 1000000LL;
    const char *origen = sensores_origen();
    uint32_t seq = 0;
    int64_t objetivo = 0;
    bool salto = false;

    for (;;) {
        bool con_hora;
        int64_t ahora = reloj_us(&con_hora);

        /* Primera vuelta, o el reloj saltó (sincronización inicial o corrección): nueva cuadrícula. */
        if (objetivo == 0 || objetivo - ahora > 2 * periodo_us || ahora - objetivo > periodo_us) {
            salto = (objetivo != 0);
            objetivo = cuadricula_siguiente(ahora, periodo_us);
        }

        /* Espera gruesa con el planificador y ajuste final de a un tick. */
        while ((ahora = reloj_us(&con_hora)) < objetivo && objetivo - ahora <= 2 * periodo_us) {
            int64_t falta_ms = (objetivo - ahora) / 1000;
            vTaskDelay(falta_ms > 30 ? pdMS_TO_TICKS(falta_ms - 20) : 1);
        }
        if (ahora < objetivo || ahora - objetivo > periodo_us) {
            continue;   /* el reloj saltó durante la espera; la vuelta siguiente rehace la cuadrícula */
        }

        muestra_t m = { 0 };
        m.seq = seq++;
        m.ts = con_hora ? objetivo / 1000000LL : 0;
        m.retraso_ms = (int32_t) ((ahora - objetivo) / 1000);
        if (!con_hora) {
            m.estado |= EST_SIN_HORA;
        }
        if (salto) {
            m.estado |= EST_SALTO;
            salto = false;
        }
        if (!mqtt_conectado) {
            m.estado |= EST_SIN_MQTT;
        }
        sensores_tomar(&m);

        imprimir_linea(&m, origen);
        publicar(&m, origen);
        led_muestra((m.estado & (EST_SHT31_FALLO | EST_CORRIENTE_FALLO | EST_AGUA_FALLO)) != 0);

        if (m.seq % (3600 / CONFIG_NODO_PERIODO_S) == 0) {   /* cada hora, para el ensayo N-07 */
            ESP_LOGI(TAG, "memoria libre %lu B (mínima %lu B); cola de salida %d B",
                     (unsigned long) esp_get_free_heap_size(), (unsigned long) esp_get_minimum_free_heap_size(),
                     esp_mqtt_client_get_outbox_size(cliente));
        }

        objetivo += periodo_us;
    }
}

void app_main(void)
{
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);

    printf("CAB," CABECERA_CSV "\n");
    ESP_LOGI(TAG, "periodo de muestreo: %d s", CONFIG_NODO_PERIODO_S);
    ESP_ERROR_CHECK(sensores_iniciar());

    eventos = xEventGroupCreate();
    led_iniciar(estado_red);
    iniciar_wifi();
    xEventGroupWaitBits(eventos, BIT_WIFI_OK, pdFALSE, pdTRUE, pdMS_TO_TICKS(30000));
    sincronizar_hora();
    iniciar_mqtt();
    xTaskCreatePinnedToCore(tarea_muestreo, "muestreo", 6144, NULL, 4, NULL, 1);
}
