/* Cálculos puros del nodo: sin dependencias de ESP-IDF, para poder probarlos en el computador
 * (ver nodo/pruebas/). */
#pragma once

#include <stdint.h>

/* CRC-8 del SHT3x: polinomio 0x31, valor inicial 0xFF, sin reflexión ni XOR final
 * (hoja de datos SHT3x-DIS). */
uint8_t crc8_sht31(const uint8_t *datos, int n);

/* Conversión de las palabras crudas del SHT3x según su hoja de datos. */
float sht31_temperatura(uint16_t crudo);
float sht31_humedad(uint16_t crudo);

/* Punto de rocío por la aproximación de Magnus sobre agua (a = 17,62; b = 243,12 °C).
 * Devuelve NAN si la HR no es positiva o si algún dato es NAN. */
float punto_rocio(float t_c, float hr_pct);

/* Acumulador para el valor eficaz de la componente alterna: se resta la media de la ventana,
 * así que un desvío residual de la polarización a VDD/2 no se suma a la corriente. */
typedef struct {
    double suma;
    double suma2;
    uint32_t n;
} rms_acum_t;

void rms_reiniciar(rms_acum_t *a);
void rms_agregar(rms_acum_t *a, double x);
double rms_ca(const rms_acum_t *a);   /* 0 si no hay muestras */

/* Siguiente instante de la cuadrícula estrictamente posterior a ahora_us. */
int64_t cuadricula_siguiente(int64_t ahora_us, int64_t periodo_us);
