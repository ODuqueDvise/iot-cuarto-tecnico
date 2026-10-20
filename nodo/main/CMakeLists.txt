idf_component_register(
    SRCS "main.c" "sensores.c" "sht31.c" "ads1115.c" "calculos.c" "led.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES nvs_flash esp_wifi esp_netif esp_event mqtt json
                  esp_driver_i2c esp_driver_gpio esp_adc esp_timer
    EMBED_TXTFILES certs/ca.crt certs/nodo.crt certs/nodo.key)
