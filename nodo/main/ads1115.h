#pragma once

#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "esp_err.h"
#include "driver/i2c_master.h"

/* Tamaño del paso con PGA de ±0,512 V: 15,625 µV por cuenta. Debe coincidir con CONFIG_CONTINUA. */
#define ADS1115_V_POR_CUENTA (0.512 / 32768.0)

/* Configura conversión continua diferencial AIN0-AIN1 a 860 muestras/s y ALERT/RDY como señal de
 * conversión lista. Debe llamarse desde la tarea que luego llama a ads1115_leer(), porque la
 * interrupción notifica a esa tarea. */
esp_err_t ads1115_iniciar(i2c_master_bus_handle_t bus, uint8_t direccion, int gpio_rdy);

/* Espera la siguiente conversión (hasta `espera` ticks) y la lee. */
esp_err_t ads1115_leer(int16_t *cuentas, TickType_t espera);
