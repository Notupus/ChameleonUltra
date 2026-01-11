#include "hex_utils.h"

/**
 * @brief Convert the large number to the hex byte array
 * @param n    : The value of the conversion
 * @param len  : The byte length of the value after the conversion is stored
 * @param dest : Caps that store conversion results
 * @retval none
 *
 */
void num_to_bytes(uint64_t n, uint8_t len, uint8_t *dest) {
    while (len--) {
        dest[len] = (uint8_t)n;
        n >>= 8;
    }
}

/**
 * @brief Convert byte array to large number
 * @param len  : The byte length of the buffer of the value of the value
 * @param src  : Byte buffer stored in the numerical
 * @retval Converting result
 *
 */
uint64_t bytes_to_num(uint8_t *src, uint8_t len) {
    uint64_t num = 0;
    while (len--) {
        num = (num << 8) | (*src);
        src++;
    }
    return num;
}

// Converts a byte array to a static hex string (uppercase, no spaces)
const char* hex_to_str(const uint8_t* data, uint16_t len) {
    static char hexstr[513]; // 256 bytes max + null
    const char hex[] = "0123456789ABCDEF";
    if (len > 256) len = 256;
    for (uint16_t i = 0; i < len; ++i) {
        hexstr[i*2] = hex[(data[i] >> 4) & 0xF];
        hexstr[i*2+1] = hex[data[i] & 0xF];
    }
    hexstr[len*2] = '\0';
    return hexstr;
}
