/* Controlador mínimo del Texas Instruments ADS1115 (SBAS444E) para la medición de corriente.
 *
 * La salida del SCT-013-050 (resistencia de carga interna, 1 V eficaz a 50 A) queda montada sobre la
 * polarización a VDD/2. AIN0 recibe la señal polarizada y AIN1 el punto medio del divisor, de modo que
 * la medición diferencial AIN0-AIN1 entrega solo la componente alterna. Con la escala de ±0,512 V el
 * pico admisible es 0,512 V, es decir unos 18 A eficaces senoidales, y cada cuenta vale 15,6 µV
 * (0,78 mA). En el intervalo de RF1 (0 a 5 A) la salida llega a 0,1 V eficaz.
 */
#include "ads1115.h"

#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_attr.h"
#include "esp_log.h"

static const char *TAG = "ads1115";
static i2c_master_dev_handle_t dispositivo;
static TaskHandle_t tarea_lectora;

#define REG_CONVERSION 0x00
#define REG_CONFIG     0x01
#define REG_UMBRAL_BAJO 0x02
#define REG_UMBRAL_ALTO 0x03
#define TIEMPO_ESPERA_I2C_MS 20

/* OS=0, MUX=000 (AIN0-AIN1), PGA=100 (±0,512 V), MODE=0 (continuo), DR=111 (860 SPS),
 * COMP_MODE=0, COMP_POL=0 (activo bajo), COMP_LAT=0, COMP_QUE=00. Con COMP_QUE=11 (valor por
 * defecto) el pin queda en alta impedancia y no habría señal de conversión lista.
 * En modo continuo el pin emite un pulso de unos 8 µs al final de cada conversión. La interrupción
 * usa el flanco de bajada, que ocurre una sola vez por pulso con cualquier polaridad. */
#define CONFIG_CONTINUA 0x08E0

static void IRAM_ATTR al_conversion_lista(void *arg)
{
    BaseType_t despertar = pdFALSE;
    vTaskNotifyGiveFromISR(tarea_lectora, &despertar);
    portYIELD_FROM_ISR(despertar);
}

static esp_err_t escribir_registro(uint8_t reg, uint16_t valor)
{
    uint8_t d[3] = { reg, (uint8_t) (valor >> 8), (uint8_t) valor };
    return i2c_master_transmit(dispositivo, d, sizeof d, TIEMPO_ESPERA_I2C_MS);
}

esp_err_t ads1115_iniciar(i2c_master_bus_handle_t bus, uint8_t direccion, int gpio_rdy)
{
    /* Se puede llamar de nuevo para reintentar: el dispositivo y la interrupción se registran una vez. */
    static bool interrupcion_lista = false;
    tarea_lectora = xTaskGetCurrentTaskHandle();
    esp_err_t r;

    if (dispositivo == NULL) {
        i2c_device_config_t cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = direccion,
            .scl_speed_hz = 400000,
        };
        if ((r = i2c_master_bus_add_device(bus, &cfg, &dispositivo)) != ESP_OK) {
            return r;
        }
    }

    if (!interrupcion_lista) {
        gpio_config_t io = {
            .pin_bit_mask = 1ULL << gpio_rdy,
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .intr_type = GPIO_INTR_NEGEDGE,
        };
        if ((r = gpio_config(&io)) != ESP_OK) {
            return r;
        }
        r = gpio_install_isr_service(0);
        if (r != ESP_OK && r != ESP_ERR_INVALID_STATE) {   /* INVALID_STATE: ya estaba instalado */
            return r;
        }
        if ((r = gpio_isr_handler_add(gpio_rdy, al_conversion_lista, NULL)) != ESP_OK) {
            return r;
        }
        interrupcion_lista = true;
    }

    /* Umbral alto con el bit más significativo en 1 y umbral bajo en 0: ALERT/RDY pasa a funcionar
     * como señal de conversión lista. */
    if ((r = escribir_registro(REG_UMBRAL_ALTO, 0x8000)) != ESP_OK ||
        (r = escribir_registro(REG_UMBRAL_BAJO, 0x0000)) != ESP_OK) {
        ESP_LOGE(TAG, "sin respuesta en 0x%02x", direccion);
        return r;
    }
    return escribir_registro(REG_CONFIG, CONFIG_CONTINUA);
}

esp_err_t ads1115_leer(int16_t *cuentas, TickType_t espera)
{
    if (ulTaskNotifyTake(pdTRUE, espera) == 0) {
        return ESP_ERR_TIMEOUT;
    }
    uint8_t reg = REG_CONVERSION, d[2];
    esp_err_t r = i2c_master_transmit_receive(dispositivo, &reg, 1, d, sizeof d, TIEMPO_ESPERA_I2C_MS);
    if (r == ESP_OK) {
        *cuentas = (int16_t) ((d[0] << 8) | d[1]);
    }
    return r;
}
