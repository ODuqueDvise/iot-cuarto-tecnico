/* Indicador de estado con el LED de la placa. Una tarea de prioridad baja recorre un ciclo de 3 s
 * en pasos de 50 ms; el patrón depende del estado de la red y de la última muestra.
 *
 *   Parpadeo rápido continuo ........ sin Wi-Fi
 *   Parpadeo lento (1 por segundo) .. Wi-Fi sin MQTT o sin hora del borde
 *   Un destello cada 3 s ............ en línea, sensores bien
 *   Tres destellos cada 3 s ......... en línea, la última muestra trae falla de algún sensor
 *   Encendido fijo 300 ms ........... se acaba de registrar una muestra (cada 30 s)
 */
#include "led.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "sdkconfig.h"

#if CONFIG_NODO_LED_GPIO >= 0

#define PASO_MS        50
#define PASOS_CICLO    (3000 / PASO_MS)
#define PASOS_MUESTRA  (300 / PASO_MS)

static led_red_t (*consultar_red)(void);
static volatile bool fallo = false;
static volatile int muestra_restante = 0;
static volatile int forzado = -1;

static bool encendido(led_red_t red, int paso)
{
    switch (red) {
    case LED_SIN_WIFI:
        return (paso / 2) % 2 == 0;                     /* 100 ms encendido, 100 ms apagado */
    case LED_SIN_SERVIDOR:
        return (paso / 10) % 2 == 0;                    /* 500 ms encendido, 500 ms apagado */
    case LED_EN_LINEA:
    default:
        if (fallo) {
            return paso == 0 || paso == 4 || paso == 8;   /* tres destellos de 50 ms */
        }
        return paso == 0;                               /* un destello de 50 ms */
    }
}

static void tarea_led(void *arg)
{
    TickType_t ultimo = xTaskGetTickCount();
    for (int paso = 0;; paso = (paso + 1) % PASOS_CICLO) {
        bool nivel;
        if (forzado >= 0) {
            nivel = forzado;
        } else if (muestra_restante > 0) {
            muestra_restante--;
            nivel = true;
        } else {
            nivel = encendido(consultar_red(), paso);
        }
        gpio_set_level(CONFIG_NODO_LED_GPIO, nivel);
        vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(PASO_MS));
    }
}

void led_iniciar(led_red_t (*consulta)(void))
{
    if (consulta == NULL) {
        return;
    }
    consultar_red = consulta;
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << CONFIG_NODO_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
    };
    if (gpio_config(&io) != ESP_OK) {
        return;
    }
    gpio_set_level(CONFIG_NODO_LED_GPIO, 0);
    /* Prioridad 1, por debajo del muestreo (4) y de la corriente; núcleo 0. */
    xTaskCreatePinnedToCore(tarea_led, "led", 2048, NULL, 1, NULL, 0);
}

void led_muestra(bool fallo_sensor)
{
    fallo = fallo_sensor;
    muestra_restante = PASOS_MUESTRA;
}

void led_forzar(int modo)
{
    forzado = modo < 0 ? -1 : (modo ? 1 : 0);
}

#else   /* LED desactivado */

void led_iniciar(led_red_t (*consulta)(void)) { (void) consulta; }
void led_muestra(bool fallo_sensor) { (void) fallo_sensor; }
void led_forzar(int modo) { (void) modo; }

#endif
