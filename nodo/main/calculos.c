#include "calculos.h"

#include <math.h>

uint8_t crc8_sht31(const uint8_t *datos, int n)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < n; i++) {
        crc ^= datos[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t) ((crc << 1) ^ 0x31) : (uint8_t) (crc << 1);
        }
    }
    return crc;
}

float sht31_temperatura(uint16_t crudo)
{
    return -45.0f + 175.0f * (float) crudo / 65535.0f;
}

float sht31_humedad(uint16_t crudo)
{
    return 100.0f * (float) crudo / 65535.0f;
}

float punto_rocio(float t_c, float hr_pct)
{
    if (isnan(t_c) || isnan(hr_pct) || hr_pct <= 0.0f) {
        return NAN;
    }
    const float a = 17.62f, b = 243.12f;
    float gamma = logf(hr_pct / 100.0f) + a * t_c / (b + t_c);
    return b * gamma / (a - gamma);
}

void rms_reiniciar(rms_acum_t *a)
{
    a->suma = 0.0;
    a->suma2 = 0.0;
    a->n = 0;
}

void rms_agregar(rms_acum_t *a, double x)
{
    a->suma += x;
    a->suma2 += x * x;
    a->n++;
}

double rms_ca(const rms_acum_t *a)
{
    if (a->n == 0) {
        return 0.0;
    }
    double media = a->suma / a->n;
    double var = a->suma2 / a->n - media * media;
    return var > 0.0 ? sqrt(var) : 0.0;
}

int64_t cuadricula_siguiente(int64_t ahora_us, int64_t periodo_us)
{
    return (ahora_us / periodo_us + 1) * periodo_us;
}
