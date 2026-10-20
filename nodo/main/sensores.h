#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* Bits de estado_sensores. Cada registro lleva los que se activaron en su intervalo. */
#define EST_SHT31_FALLO     (1u << 0)   /* lectura fallida o CRC inválido */
#define EST_CORRIENTE_FALLO (1u << 1)   /* alguna ventana de 1 s sin conversiones suficientes */
#define EST_AGUA_FALLO      (1u << 2)   /* lectura del ADC fallida */
#define EST_SIN_HORA        (1u << 3)   /* el reloj no está sincronizado con el borde */
#define EST_SALTO           (1u << 4)   /* la cuadrícula se recalculó (reloj corregido o atraso) */
#define EST_SIN_MQTT        (1u << 5)   /* sin conexión al registrar: el mensaje queda en la cola */

typedef struct {
    uint32_t seq;            /* avanza en cada muestra tomada, haya o no conexión */
    int64_t ts;              /* instante nominal de la cuadrícula, s desde 1970; 0 sin hora */
    int32_t retraso_ms;      /* diferencia entre el instante real y el nominal */
    float t_c;               /* NAN si no hay dato */
    float hr_pct;
    float pr_c;              /* punto de rocío */
    float i_media_a;         /* media de los valores eficaces de 1 s del intervalo */
    float i_max_a;           /* máximo de esos valores */
    int8_t puerta;           /* 1 abierta, 0 cerrada, -1 sin dato */
    uint16_t puerta_aperturas;  /* aperturas durante el intervalo */
    int8_t agua;             /* 1 presencia de agua, 0 seco, -1 sin dato */
    uint16_t agua_eventos;   /* transiciones de seco a mojado durante el intervalo */
    uint32_t estado;         /* bits EST_* */
} muestra_t;

esp_err_t sensores_iniciar(void);

/* Lee temperatura y HR, toma lo acumulado desde la muestra anterior (corriente, aperturas, eventos)
 * y reinicia los acumuladores. No toca seq, ts, retraso_ms ni los bits de reloj y conexión. */
void sensores_tomar(muestra_t *m);

/* "sensor" si ningún sensor está en modo simulado; "simulado" en otro caso. */
const char *sensores_origen(void);
