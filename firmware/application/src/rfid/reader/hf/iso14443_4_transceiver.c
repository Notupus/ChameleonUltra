#include "iso14443_4_transceiver.h"
#include "rc522.h"
#include "rfid_main.h"
#include "nrf_log.h"
#include <string.h>

static uint8_t g_pcb_block_num = 0;

void iso14443_4_reset_block_num(void) {
    g_pcb_block_num = 0;
}

bool iso14443_4_transceive(uint8_t *tx_data, uint16_t tx_len, uint8_t *rx_data, uint16_t *rx_len, uint16_t max_rx_len) {
    uint8_t buffer[260]; 
    uint16_t rx_bits = 0;
    uint8_t status;

    // Construct I-Block
    buffer[0] = 0x02 | (g_pcb_block_num & 0x01);
    memcpy(&buffer[1], tx_data, tx_len);
    
    // Append CRC manually
    crc_14a_append(buffer, 1 + tx_len);
    
    uint16_t frame_len = 1 + tx_len + 2; 
    
    int wtx_count = 0;
    const int WTX_MAX = 10; // Limit to avoid infinite loops
    while (1) {
        if (status != STATUS_HF_TAG_OK || rx_bits < (3 * 8)) {
            return false;
        }
        uint16_t rx_bytes = rx_bits / 8;
        // Verify CRC
        uint8_t crc_calc[2];
        crc_14a_calculate(buffer, rx_bytes - 2, crc_calc);
        if (buffer[rx_bytes - 2] != crc_calc[0] || buffer[rx_bytes - 1] != crc_calc[1]) {
            return false;
        }
        uint8_t pcb_type = buffer[0] & 0xC0;
        if (pcb_type == 0x00) {
            // I-Block (normal data)
            g_pcb_block_num ^= 1;
            if (rx_bytes - 3 > max_rx_len) {
                return false;
            }
            *rx_len = rx_bytes - 3;
            memcpy(rx_data, &buffer[1], *rx_len);
            return true;
        } else if (pcb_type == 0xC0) {
            // S-Block (WTX or DESELECT)
            if ((buffer[0] & 0x3F) == 0x32 && rx_bytes >= 4) {
                // WTX request: S(WTXm)
                uint8_t wtxm = buffer[1];
                uint8_t wtx_resp[4];
                wtx_resp[0] = 0xF2;
                wtx_resp[1] = wtxm;
                crc_14a_append(wtx_resp, 2);
                uint16_t wtx_resp_len = 4;
                // Send WTX response
                uint16_t wtx_rx_bits = 0;
                uint8_t wtx_status = pcd_14a_reader_bytes_transfer(PCD_TRANSCEIVE, wtx_resp, wtx_resp_len, buffer, &wtx_rx_bits, sizeof(buffer) * 8);
                status = wtx_status;
                rx_bits = wtx_rx_bits;
                wtx_count++;
                if (wtx_count > WTX_MAX) {
                    return false;
                }
                continue; // Wait for next frame
            } else {
                // Other S-Blocks (not handled)
                return false;
            }
        } else {
            // R-Block or unknown (not handled)
            return false;
        }
    }
}
