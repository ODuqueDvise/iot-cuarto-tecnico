idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES nvs_flash esp_wifi esp_netif esp_event mqtt json
    EMBED_TXTFILES certs/ca.crt certs/nodo.crt certs/nodo.key)
