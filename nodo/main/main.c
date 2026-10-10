/* Nodo del cuarto técnico. Etapa 1: conectividad y telemetría simulada.
 *
 * Wi-Fi en modo estación, hora por SNTP desde el borde, MQTT 5.0 sobre TLS con certificado
 * de cliente, mensaje de última voluntad y publicación cada PERIODO_TELEMETRIA_MS.
 * Los valores de los sensores son simulados hasta que lleguen los componentes.
 */
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "cJSON.h"

#include "secretos.h"

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
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG(SNTP_SERVIDOR);
    ESP_ERROR_CHECK(esp_netif_sntp_init(&cfg));
    if (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(15000)) == ESP_OK) {
        time_t ahora = time(NULL);
        ESP_LOGI(TAG, "hora sincronizada con el borde: %lld", (long long) ahora);
    } else {
        ESP_LOGW(TAG, "sin hora del borde; las marcas de tiempo las pondrá el puente");
    }
}

/* ---------- MQTT ---------- */
static void manejador_mqtt(void *arg, esp_event_base_t base, int32_t id, void *datos)
{
    esp_mqtt_event_handle_t ev = datos;
    switch ((esp_mqtt_event_id_t) id) {
    case MQTT_EVENT_CONNECTED:
        mqtt_conectado = true;
        ESP_LOGI(TAG, "MQTT conectado");
        esp_mqtt_client_publish(cliente, tema_estado, "en_linea", 0, 1, 1);
        esp_mqtt_client_subscribe(cliente, tema_comandos, 2);
        break;
    case MQTT_EVENT_DISCONNECTED:
        mqtt_conectado = false;
        ESP_LOGW(TAG, "MQTT desconectado");
        break;
    case MQTT_EVENT_DATA:
        ESP_LOGI(TAG, "comando en %.*s: %.*s", ev->topic_len, ev->topic, ev->data_len, ev->data);
        /* Etapa 2: interpretar comandos (umbrales, horarios). Las reglas duras no se anulan desde aquí. */
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
    };
    cliente = esp_mqtt_client_init(&cfg);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(cliente, ESP_EVENT_ANY_ID, manejador_mqtt, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(cliente));
}

/* ---------- Telemetría ---------- */
static void tarea_telemetria(void *arg)
{
    uint32_t seq = 0;
    for (;;) {
        xEventGroupWaitBits(eventos, BIT_WIFI_OK, pdFALSE, pdTRUE, portMAX_DELAY);
        if (mqtt_conectado) {
            cJSON *j = cJSON_CreateObject();
            cJSON_AddStringToObject(j, "nodo", NODO_ID);
            cJSON_AddNumberToObject(j, "ts", (double) time(NULL));
            cJSON_AddNumberToObject(j, "seq", seq);
            /* Valores simulados con una variación lenta, para ver algo en el panel. */
            cJSON_AddNumberToObject(j, "t",  22.0 + (seq % 60) * 0.05);
            cJSON_AddNumberToObject(j, "hr", 48.0 + (seq % 20) * 0.2);
            cJSON_AddNumberToObject(j, "i",  1.40 + (seq % 10) * 0.01);
            cJSON_AddBoolToObject(j, "puerta", false);
            cJSON_AddBoolToObject(j, "agua", false);
            cJSON_AddStringToObject(j, "origen", "simulado");

            char *s = cJSON_PrintUnformatted(j);
            int id = esp_mqtt_client_publish(cliente, tema_telemetria, s, 0, 1, 0);
            ESP_LOGI(TAG, "telemetria %lu publicada (id %d, %d bytes)", (unsigned long) seq, id, (int) strlen(s));
            cJSON_free(s);
            cJSON_Delete(j);
            seq++;
        }
        vTaskDelay(pdMS_TO_TICKS(PERIODO_TELEMETRIA_MS));
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

    eventos = xEventGroupCreate();
    iniciar_wifi();
    xEventGroupWaitBits(eventos, BIT_WIFI_OK, pdFALSE, pdTRUE, portMAX_DELAY);
    sincronizar_hora();
    iniciar_mqtt();
    xTaskCreate(tarea_telemetria, "telemetria", 4096, NULL, 5, NULL);
}
