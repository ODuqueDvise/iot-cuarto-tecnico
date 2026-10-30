/* Indicador de estado con el LED de la placa (un solo LED, estados por patrón de parpadeo). */
#pragma once

#include <stdbool.h>

typedef enum {
    LED_SIN_WIFI,       /* parpadeo rápido (5 por segundo) */
    LED_SIN_SERVIDOR,   /* Wi-Fi conectado, pero sin MQTT o sin hora: parpadeo lento (1 por segundo) */
    LED_EN_LINEA,       /* todo conectado: un destello corto cada 3 s; tres destellos si falla un sensor */
} led_red_t;

/* Arranca la tarea del LED. `consulta` devuelve el estado de la red; se llama cada 50 ms y no debe
 * bloquear. Sin efecto si CONFIG_NODO_LED_GPIO es -1. */
void led_iniciar(led_red_t (*consulta)(void));

/* Avisa que se registró una muestra: encendido fijo 300 ms. `fallo_sensor` queda vigente hasta la
 * muestra siguiente y cambia el latido de uno a tres destellos. */
void led_muestra(bool fallo_sensor);

/* Modo forzado por comando: 0 apagado, 1 encendido, -1 automático (los patrones de arriba). */
void led_forzar(int modo);
