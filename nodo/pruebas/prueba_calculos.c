/* Pruebas de los cálculos puros del nodo. Se compilan y ejecutan en el computador:
 *   cc -std=gnu11 -I../main prueba_calculos.c ../main/calculos.c -lm -o prueba && ./prueba
 */
#include <assert.h>
#include <math.h>
#include <stdio.h>

#include "calculos.h"

static int fallos = 0;

static void cerca(const char *nombre, double obtenido, double esperado, double tol)
{
    int ok = fabs(obtenido - esperado) <= tol;
    printf("%-44s %s  obtenido %.4f, esperado %.4f\n", nombre, ok ? "ok   " : "FALLA", obtenido, esperado);
    fallos += !ok;
}

int main(void)
{
    /* Ejemplo de la hoja de datos del SHT3x: CRC(0xBEEF) = 0x92. */
    const uint8_t beef[2] = { 0xBE, 0xEF };
    cerca("CRC-8 de 0xBEEF", crc8_sht31(beef, 2), 0x92, 0);

    cerca("temperatura con crudo 0", sht31_temperatura(0), -45.0, 1e-4);
    cerca("temperatura con crudo 65535", sht31_temperatura(65535), 130.0, 1e-4);
    cerca("HR con crudo 32768", sht31_humedad(32768), 50.0008, 1e-3);

    /* Valor de referencia de la fórmula de Magnus con a = 17,62 y b = 243,12: 25 °C y 50 % HR dan
     * un punto de rocío cercano a 13,85 °C. */
    cerca("punto de rocío 25 °C, 50 % HR", punto_rocio(25.0f, 50.0f), 13.85, 0.05);
    cerca("punto de rocío 20 °C, 100 % HR (igual a T)", punto_rocio(20.0f, 100.0f), 20.0, 1e-3);
    cerca("punto de rocío con HR 0 (NAN)", isnan(punto_rocio(20.0f, 0.0f)), 1, 0);

    /* Seno de 60 Hz con amplitud 1000 cuentas y desvío de 300, muestreado a 860/s durante 1 s:
     * el valor eficaz de la componente alterna debe ser 1000/sqrt(2) aunque haya desvío. */
    rms_acum_t a;
    rms_reiniciar(&a);
    for (int k = 0; k < 860; k++) {
        rms_agregar(&a, 300.0 + 1000.0 * sin(2 * M_PI * 60.0 * k / 860.0));
    }
    cerca("RMS de seno con desvío", rms_ca(&a), 1000.0 / sqrt(2.0), 2.0);
    rms_reiniciar(&a);
    cerca("RMS sin muestras", rms_ca(&a), 0.0, 0);

    /* Cuadrícula de 30 s. */
    const int64_t P = 30000000;
    cerca("cuadrícula 7 s después de una marca", (double) cuadricula_siguiente(1791700807000000LL, P), 1791700830000000.0, 0);
    cerca("cuadrícula justo en el borde avanza", (double) cuadricula_siguiente(1791700830000000LL, P), 1791700860000000.0, 0);

    printf(fallos ? "\n%d pruebas fallaron\n" : "\nTodas las pruebas pasaron\n", fallos);
    return fallos != 0;
}
