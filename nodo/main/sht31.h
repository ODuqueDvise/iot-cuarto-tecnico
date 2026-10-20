#pragma once

#include <stdint.h>
#include "esp_err.h"
#include "driver/i2c_master.h"

esp_err_t sht31_iniciar(i2c_master_bus_handle_t bus, uint8_t direccion);

/* Medición única de alta repetibilidad sin estiramiento de reloj; verifica el CRC de ambas palabras. */
esp_err_t sht31_medir(float *t_c, float *hr_pct);
