/* Capa de sensores del nodo.
 *
 * Cada sensor se compila en modo real, simulado o ausente (menú "Nodo del cuarto técnico").
 * - Corriente: una tarea calcula el valor eficaz cada segundo (ventanas de 1 s, RF1) y lo acumula.
 * - Puerta y agua: una tarea lee la puerta cada 50 ms y la sonda cada 1 s, con antirrebote, y
 *   cuenta aperturas y eventos para que una apertura corta entre dos muestras no se pierda.
 * - Temperatura y HR: se leen en el instante de la muestra.
 * sensores_tomar() entrega lo acumulado desde la muestra anterior y reinicia los acumuladores.
 */
#include "sensores.h"

#include <math.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_rom_sys.h"
#include "sdkconfig.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"

#include "calculos.h"
#include "sht31.h"
#include "ads1115.h"

static const char *TAG = "sensores";

#if defined(CONFIG_NODO_SHT31_REAL) || defined(CONFIG_NODO_CORRIENTE_REAL)
#define USA_I2C 1
#endif
#if !defined(CONFIG_NODO_PUERTA_AUSENTE) || !defined(CONFIG_NODO_AGUA_AUSENTE)
#define USA_ENTRADAS 1
#endif

/* Acumuladores del intervalo en curso, protegidos por el cerrojo. */
static portMUX_TYPE cerrojo = portMUX_INITIALIZER_UNLOCKED;
static struct {
    double i_suma;
    float i_max;
    uint32_t i_n;
    uint32_t i_fallos;
    uint16_t puerta_aperturas;
    uint16_t agua_eventos;
    bool agua_fallo;
    int8_t puerta;      /* -1 hasta la primera lectura */
    int8_t agua;
} acum = { .puerta = -1, .agua = -1 };

__attribute__((unused)) static double segundos(void)
{
    return esp_timer_get_time() / 1e6;
}

__attribute__((unused)) static float ruido(float amplitud)
{
    return amplitud * ((float) esp_random() / (float) UINT32_MAX * 2.0f - 1.0f);
}

/* ---------- Bus I2C ---------- */
#ifdef USA_I2C
static i2c_master_bus_handle_t bus;

static esp_err_t iniciar_i2c(void)
{
    i2c_master_bus_config_t c = {
        .i2c_port = -1,
        .sda_io_num = CONFIG_NODO_I2C_SDA,
        .scl_io_num = CONFIG_NODO_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,   /* las placas suelen traer pull-up de 10 kOhm */
    };
    esp_err_t r = i2c_new_master_bus(&c, &bus);
    if (r != ESP_OK) {
        return r;
    }
    int hallados = 0;
    for (uint16_t dir = 0x08; dir < 0x78; dir++) {
        if (i2c_master_probe(bus, dir, 20) == ESP_OK) {
            ESP_LOGI(TAG, "dispositivo I2C en 0x%02x", dir);
            hallados++;
        }
    }
    if (hallados == 0) {
        ESP_LOGW(TAG, "ningún dispositivo responde en el bus I2C");
    }
    return ESP_OK;
}
#endif

/* ---------- Corriente ---------- */
#ifndef CONFIG_NODO_CORRIENTE_AUSENTE
static void registrar_corriente(float i)
{
    taskENTER_CRITICAL(&cerrojo);
    if (isnan(i)) {
        acum.i_fallos++;
    } else {
        acum.i_suma += i;
        if (acum.i_n == 0 || i > acum.i_max) {
            acum.i_max = i;
        }
        acum.i_n++;
    }
    taskEXIT_CRITICAL(&cerrojo);
}
#endif

#ifdef CONFIG_NODO_CORRIENTE_REAL
/* A 860 muestras/s nominales (±10 % según la hoja de datos) una ventana de 1 s trae unas 800;
 * menos de 500 indica que faltan conversiones. */
#define MIN_MUESTRAS_VENTANA 500
#define MAX_FALLOS_VENTANA   20

static void tarea_corriente(void *arg)
{
    const double a_por_v = CONFIG_NODO_CT_MA_POR_V / 1000.0 / CONFIG_NODO_CT_VUELTAS;
    while (ads1115_iniciar(bus, CONFIG_NODO_ADS1115_DIR, CONFIG_NODO_ADS1115_RDY) != ESP_OK) {
        registrar_corriente(NAN);
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
    rms_acum_t a;
    for (;;) {
        rms_reiniciar(&a);
        int fallos = 0;
        int64_t fin = esp_timer_get_time() + 1000000;
        while (esp_timer_get_time() < fin && fallos < MAX_FALLOS_VENTANA) {
            int16_t c;
            if (ads1115_leer(&c, pdMS_TO_TICKS(20)) == ESP_OK) {
                rms_agregar(&a, c);
            } else {
                fallos++;
            }
        }
        if (a.n >= MIN_MUESTRAS_VENTANA) {
            registrar_corriente((float) (rms_ca(&a) * ADS1115_V_POR_CUENTA * a_por_v));
        } else {
            registrar_corriente(NAN);
            ESP_LOGW(TAG, "ventana de corriente con %lu conversiones y %d fallos; se reconfigura el ADS1115",
                     (unsigned long) a.n, fallos);
            vTaskDelay(pdMS_TO_TICKS(1000));
            ads1115_iniciar(bus, CONFIG_NODO_ADS1115_DIR, CONFIG_NODO_ADS1115_RDY);
        }
    }
}
#elif defined(CONFIG_NODO_CORRIENTE_SIMULADO)
static void tarea_corriente(void *arg)
{
    TickType_t ultimo = xTaskGetTickCount();
    for (;;) {
        double s = segundos();
        registrar_corriente(1.4f + 0.3f * sinf(2.0f * (float) M_PI * (float) (s / 900.0)) + ruido(0.02f));
        vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(1000));
    }
}
#endif

/* ---------- Puerta y agua ---------- */
#ifdef USA_ENTRADAS
typedef struct {
    int8_t estado;      /* -1 sin lectura */
    int8_t candidato;
    uint8_t cuenta;
} antirrebote_t;

/* Cambia de estado tras n lecturas iguales y distintas del estado vigente.
 * Devuelve true solo en la transición de 0 a 1 (apertura o llegada de agua). */
static bool antirrebote(antirrebote_t *a, int lectura, uint8_t n)
{
    if (a->estado < 0) {
        a->estado = (int8_t) lectura;
        a->candidato = (int8_t) lectura;
        a->cuenta = 0;
        return false;
    }
    if (lectura == a->estado) {
        a->cuenta = 0;
        return false;
    }
    if (lectura != a->candidato) {
        a->candidato = (int8_t) lectura;
        a->cuenta = 1;
    } else {
        a->cuenta++;
    }
    if (a->cuenta >= n) {
        a->estado = (int8_t) lectura;
        a->cuenta = 0;
        return lectura == 1;
    }
    return false;
}

#ifdef CONFIG_NODO_AGUA_REAL
static adc_oneshot_unit_handle_t adc;
static adc_channel_t canal_agua;
static adc_cali_handle_t cali_agua;
static bool cali_lista;

static esp_err_t iniciar_agua(void)
{
    gpio_config_t exc = {
        .pin_bit_mask = 1ULL << CONFIG_NODO_AGUA_EXC_GPIO,
        .mode = GPIO_MODE_OUTPUT,
    };
    esp_err_t r = gpio_config(&exc);
    if (r != ESP_OK) {
        return r;
    }
    gpio_set_level(CONFIG_NODO_AGUA_EXC_GPIO, 0);

    adc_unit_t unidad;
    if ((r = adc_oneshot_io_to_channel(CONFIG_NODO_AGUA_ADC_GPIO, &unidad, &canal_agua)) != ESP_OK) {
        return r;
    }
    if (unidad != ADC_UNIT_1) {
        ESP_LOGE(TAG, "el GPIO %d no es de ADC1; ADC2 no funciona con Wi-Fi activo", CONFIG_NODO_AGUA_ADC_GPIO);
        return ESP_ERR_INVALID_ARG;
    }
    adc_oneshot_unit_init_cfg_t uc = { .unit_id = ADC_UNIT_1 };
    if ((r = adc_oneshot_new_unit(&uc, &adc)) != ESP_OK) {
        return r;
    }
    adc_oneshot_chan_cfg_t cc = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
    if ((r = adc_oneshot_config_channel(adc, canal_agua, &cc)) != ESP_OK) {
        return r;
    }
#if ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    adc_cali_line_fitting_config_t lc = {
        .unit_id = ADC_UNIT_1,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
#if CONFIG_IDF_TARGET_ESP32
        .default_vref = 1100,   /* solo se usa si el eFuse no trae la referencia */
#endif
    };
    cali_lista = adc_cali_create_scheme_line_fitting(&lc, &cali_agua) == ESP_OK;
#endif
    if (!cali_lista) {
        ESP_LOGW(TAG, "ADC sin calibración; se usa una conversión aproximada a mV");
    }
    return ESP_OK;
}

/* Excita la sonda con un pulso corto (evita la electrólisis de los electrodos) y lee el divisor.
 * Devuelve 1 mojado, 0 seco, -1 si la lectura falla. */
static int leer_agua(void)
{
    int crudo, mv;
    gpio_set_level(CONFIG_NODO_AGUA_EXC_GPIO, 1);
    esp_rom_delay_us(500);
    esp_err_t r = adc_oneshot_read(adc, canal_agua, &crudo);
    gpio_set_level(CONFIG_NODO_AGUA_EXC_GPIO, 0);
    if (r != ESP_OK) {
        return -1;
    }
    if (!cali_lista || adc_cali_raw_to_voltage(cali_agua, crudo, &mv) != ESP_OK) {
        mv = crudo * 3100 / 4095;
    }
    return mv > CONFIG_NODO_AGUA_UMBRAL_MV ? 1 : 0;
}
#endif

static void tarea_entradas(void *arg)
{
    antirrebote_t puerta = { .estado = -1 }, agua = { .estado = -1 };
    TickType_t ultimo = xTaskGetTickCount();
    uint32_t vuelta = 0;
    (void) puerta;
    (void) agua;

    for (;; vuelta++) {
        bool apertura = false, evento_agua = false, fallo_agua = false;

#ifdef CONFIG_NODO_PUERTA_REAL
#ifdef CONFIG_NODO_PUERTA_INVERTIDA
        apertura = antirrebote(&puerta, !gpio_get_level(CONFIG_NODO_PUERTA_GPIO), 3);
#else
        apertura = antirrebote(&puerta, gpio_get_level(CONFIG_NODO_PUERTA_GPIO), 3);
#endif
#elif defined(CONFIG_NODO_PUERTA_SIMULADO)
        apertura = antirrebote(&puerta, ((int64_t) segundos() % 600) < 20, 3);   /* 20 s cada 10 min */
#endif

        if (vuelta % 20 == 0) {   /* cada 1 s */
#ifdef CONFIG_NODO_AGUA_REAL
            int l = leer_agua();
            if (l < 0) {
                fallo_agua = true;
            } else {
                evento_agua = antirrebote(&agua, l, 2);
            }
#elif defined(CONFIG_NODO_AGUA_SIMULADO)
            evento_agua = antirrebote(&agua, ((int64_t) segundos() % 1800) < 60, 2);   /* 60 s cada 30 min */
#endif
        }

        taskENTER_CRITICAL(&cerrojo);
#ifndef CONFIG_NODO_PUERTA_AUSENTE
        acum.puerta = puerta.estado;
        if (apertura) {
            acum.puerta_aperturas++;
        }
#endif
#ifndef CONFIG_NODO_AGUA_AUSENTE
        acum.agua = agua.estado;
        if (evento_agua) {
            acum.agua_eventos++;
        }
        if (fallo_agua) {
            acum.agua_fallo = true;
        }
#endif
        taskEXIT_CRITICAL(&cerrojo);

        vTaskDelayUntil(&ultimo, pdMS_TO_TICKS(50));
    }
}
#endif

/* ---------- Interfaz ---------- */
esp_err_t sensores_iniciar(void)
{
#ifdef USA_I2C
    esp_err_t r = iniciar_i2c();
    if (r != ESP_OK) {
        ESP_LOGE(TAG, "no se pudo crear el bus I2C: %s", esp_err_to_name(r));
        return r;
    }
#endif
#ifdef CONFIG_NODO_SHT31_REAL
    sht31_iniciar(bus, CONFIG_NODO_SHT31_DIR);   /* si falla, cada muestra lo marca con EST_SHT31_FALLO */
#endif
#ifdef CONFIG_NODO_PUERTA_REAL
    gpio_config_t p = {
        .pin_bit_mask = 1ULL << CONFIG_NODO_PUERTA_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&p));
#endif
#ifdef CONFIG_NODO_AGUA_REAL
    if (iniciar_agua() != ESP_OK) {
        ESP_LOGE(TAG, "no se pudo preparar la sonda de agua; las muestras lo marcarán con EST_AGUA_FALLO");
    }
#endif
#ifndef CONFIG_NODO_CORRIENTE_AUSENTE
    /* Núcleo 1, lejos de la pila Wi-Fi; la interrupción del ADS1115 queda en el mismo núcleo. */
    xTaskCreatePinnedToCore(tarea_corriente, "corriente", 3072, NULL, 6, NULL, 1);
#endif
#ifdef USA_ENTRADAS
    xTaskCreatePinnedToCore(tarea_entradas, "entradas", 3072, NULL, 5, NULL, 1);
#endif
    ESP_LOGI(TAG, "origen de los datos: %s", sensores_origen());
    return ESP_OK;
}

void sensores_tomar(muestra_t *m)
{
    m->t_c = NAN;
    m->hr_pct = NAN;
    m->i_media_a = NAN;
    m->i_max_a = NAN;

#ifdef CONFIG_NODO_SHT31_REAL
    float t, h;
    esp_err_t r = sht31_medir(&t, &h);
    if (r != ESP_OK) {
        r = sht31_medir(&t, &h);   /* un reintento */
    }
    if (r == ESP_OK) {
        m->t_c = t;
        m->hr_pct = h;
    } else {
        m->estado |= EST_SHT31_FALLO;
    }
#elif defined(CONFIG_NODO_SHT31_SIMULADO)
    float fase = 2.0f * (float) M_PI * (float) (segundos() / 3600.0);
    m->t_c = 22.0f + 1.5f * sinf(fase) + ruido(0.05f);
    m->hr_pct = 50.0f - 5.0f * sinf(fase) + ruido(0.3f);
#endif
    m->pr_c = punto_rocio(m->t_c, m->hr_pct);

    taskENTER_CRITICAL(&cerrojo);
    double i_suma = acum.i_suma;
    float i_max = acum.i_max;
    uint32_t i_n = acum.i_n, i_fallos = acum.i_fallos;
    m->puerta = acum.puerta;
    m->puerta_aperturas = acum.puerta_aperturas;
    m->agua = acum.agua;
    m->agua_eventos = acum.agua_eventos;
    bool agua_fallo = acum.agua_fallo;
    acum.i_suma = 0.0;
    acum.i_max = 0.0f;
    acum.i_n = 0;
    acum.i_fallos = 0;
    acum.puerta_aperturas = 0;
    acum.agua_eventos = 0;
    acum.agua_fallo = false;
    taskEXIT_CRITICAL(&cerrojo);

#ifndef CONFIG_NODO_CORRIENTE_AUSENTE
    if (i_n > 0) {
        m->i_media_a = (float) (i_suma / i_n);
        m->i_max_a = i_max;
    }
    if (i_n == 0 || i_fallos > 0) {
        m->estado |= EST_CORRIENTE_FALLO;
    }
#else
    (void) i_suma;
    (void) i_max;
    (void) i_n;
    (void) i_fallos;
#endif
    if (agua_fallo) {
        m->estado |= EST_AGUA_FALLO;
    }
}

const char *sensores_origen(void)
{
#if defined(CONFIG_NODO_SHT31_SIMULADO) || defined(CONFIG_NODO_CORRIENTE_SIMULADO) || \
    defined(CONFIG_NODO_PUERTA_SIMULADO) || defined(CONFIG_NODO_AGUA_SIMULADO)
    return "simulado";
#else
    return "sensor";
#endif
}
