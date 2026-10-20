/* Controlador mínimo del Sensirion SHT3x-DIS por I2C (hoja de datos SHT3x-DIS, versión 7). */
#include "sht31.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

#include "calculos.h"

static const char *TAG = "sht31";
static i2c_master_dev_handle_t dispositivo;

#define TIEMPO_ESPERA_I2C_MS 50

esp_err_t sht31_iniciar(i2c_master_bus_handle_t bus, uint8_t direccion)
{
    /* El dispositivo se registra aunque el sensor no responda todavía: si se conecta después,
     * sht31_medir() empieza a funcionar sin reiniciar el nodo. */
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = direccion,
        .scl_speed_hz = 400000,
    };
    esp_err_t r = i2c_master_bus_add_device(bus, &cfg, &dispositivo);
    if (r != ESP_OK) {
        dispositivo = NULL;
        return r;
    }
    /* Reinicio por programa (0x30A2). */
    const uint8_t reinicio[2] = { 0x30, 0xA2 };
    r = i2c_master_transmit(dispositivo, reinicio, sizeof reinicio, TIEMPO_ESPERA_I2C_MS);
    vTaskDelay(pdMS_TO_TICKS(10));
    if (r != ESP_OK) {
        ESP_LOGE(TAG, "sin respuesta en 0x%02x", direccion);
    }
    return r;
}

esp_err_t sht31_medir(float *t_c, float *hr_pct)
{
    if (dispositivo == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    /* Medición única, repetibilidad alta, sin estiramiento de reloj (0x2400). La espera de 20 ms
     * cubre el tiempo máximo de medición de esa repetibilidad. */
    const uint8_t orden[2] = { 0x24, 0x00 };
    esp_err_t r = i2c_master_transmit(dispositivo, orden, sizeof orden, TIEMPO_ESPERA_I2C_MS);
    if (r != ESP_OK) {
        return r;
    }
    vTaskDelay(pdMS_TO_TICKS(20));

    uint8_t d[6];
    r = i2c_master_receive(dispositivo, d, sizeof d, TIEMPO_ESPERA_I2C_MS);
    if (r != ESP_OK) {
        return r;
    }
    if (crc8_sht31(&d[0], 2) != d[2] || crc8_sht31(&d[3], 2) != d[5]) {
        ESP_LOGW(TAG, "CRC inválido");
        return ESP_ERR_INVALID_CRC;
    }
    *t_c = sht31_temperatura((uint16_t) ((d[0] << 8) | d[1]));
    *hr_pct = sht31_humedad((uint16_t) ((d[3] << 8) | d[4]));
    return ESP_OK;
}
