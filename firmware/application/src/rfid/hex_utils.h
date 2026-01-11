#ifndef __HEX_UTILS_H__
#define __HEX_UTILS_H__

#include <stdint.h>

void num_to_bytes(uint64_t n, uint8_t len, uint8_t *dest);
uint64_t bytes_to_num(uint8_t *src, uint8_t len);

// Converts a byte array to a static hex string (uppercase, no spaces)
const char* hex_to_str(const uint8_t* data, uint16_t len);

#endif
