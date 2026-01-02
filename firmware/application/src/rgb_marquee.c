#include "math.h"
#include "nrf_gpio.h"
#include "hw_connect.h"
#include "bsp_delay.h"
#include "rgb_marquee.h"
#include "bsp_time.h"
#include "app_timer.h"


#define NRF_LOG_MODULE_NAME rgb
#include "nrf_log.h"
#include "nrf_log_ctrl.h"
#include "nrf_log_default_backends.h"
NRF_LOG_MODULE_REGISTER();


#define PWM_MAX 1000 // PWM Maximum
#define LIGHT_LEVEL_MAX 99 // The maximum value of brightness level
static nrf_drv_pwm_t pwm0_ins = NRF_DRV_PWM_INSTANCE(1);
nrf_pwm_values_individual_t pwm_sequ_val; // PWM control 4 channels in the independent mode
nrf_pwm_sequence_t const seq = { //Configure the structure of PWM output
    .values.p_individual = &pwm_sequ_val,
    .length          = 4,
    .repeats         = 0,
    .end_delay       = 0
};
nrf_drv_pwm_config_t pwm_config = {//PWM configuration structure
    .irq_priority = APP_IRQ_PRIORITY_LOWEST,
    .base_clock = NRF_PWM_CLK_1MHz,
    .count_mode = NRF_PWM_MODE_UP,
    .top_value = PWM_MAX,
    .load_mode = NRF_PWM_LOAD_INDIVIDUAL, // 4 channels for four values
    .step_mode = NRF_PWM_STEP_AUTO
};
static autotimer *timer;
static uint8_t ledblink6_step = 0;
static uint8_t ledblink6_color = RGB_RED;
static uint8_t ledblink1_step = 0;
extern bool g_usb_led_marquee_enable;


void rgb_marquee_init(void) {
    timer = bsp_obtain_timer(0);
}

void rgb_marquee_stop(void) {
    nrfx_pwm_stop(&pwm0_ins, true);
    nrfx_pwm_uninit(&pwm0_ins);//turn off pwm output
    ledblink6_step = 0;
    ledblink1_step = 0;
}

// reset RGB state machines to force a refresh of the LED color
void rgb_marquee_reset(void) {
    ledblink6_step = 0;
    ledblink1_step = 0;
}

// Brightness to PWM value
uint16_t get_pwmduty(uint8_t light_level) {
    return PWM_MAX - (PWM_MAX * pow(((double)light_level / LIGHT_LEVEL_MAX), 2.2));
}

// 4 Lights and the level of brightness levels (no return)
//COLOR 0-R,1-G,2-B
void ledblink1(uint8_t color, uint8_t dir) {
    static uint8_t startled = 0;
    static uint8_t setled = 0;
    uint32_t *led_pins_arr;

    if (!g_usb_led_marquee_enable && ledblink1_step != 0) {
        startled = 0;
        setled = 0;
        rgb_marquee_stop();
        return;
    }

    //Processing direction
    if (dir == 0) {
        led_pins_arr = hw_get_led_array();
    } else {
        led_pins_arr = hw_get_led_reversal_array();
    }

    if (ledblink1_step == 0) {
        //Adjust the color
        set_slot_light_color(color);
        pwm_sequ_val.channel_0 = 1;
        pwm_sequ_val.channel_1 = 1;
        pwm_sequ_val.channel_2 = 1;
        pwm_sequ_val.channel_3 = 1;
        bsp_set_timer(timer, 0);
        ledblink1_step = 1;

        // Reset the state of the light when the USB is turned on to open the communication
        ledblink6_step = 0;
    }

    if (ledblink1_step == 1) {
        setled = startled;
        for (uint8_t i = 0; i < 4; i++) {
            pwm_config.output_pins[i] = led_pins_arr[setled];
            setled++;
            if (setled > 7)setled = 0;
        }
        startled++;
        if (startled > 7)startled = 0;
        nrfx_pwm_uninit(&pwm0_ins);
        nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
        nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);

        bsp_set_timer(timer, 0);
        ledblink1_step = 2;
    }

    if (ledblink1_step == 2) {
        if (!(NO_TIMEOUT_1MS(timer, 80))) {
            ledblink1_step = 1;
        }
    }
}

// 4 Lights Dragon Tail horizontal movement cycle (not returning), including the disappearance of the tail and the head of the head slowly
//dir 0-from 1 card slot to 8 card slot, 1-from 8 card slot to 1 card slot (Direction, the end point is determined by the END parameter)
//end To scan the number of lamps, decide the final animation area with the direction
void ledblink2(uint8_t color, uint8_t dir, uint8_t end) {
    uint8_t startled = 0;
    uint8_t setled = 0;
    uint8_t leds2turnon = 0;
    uint8_t i = 0;
    uint32_t *led_pins_arr;
    //Processing direction
    if (dir == 0) {
        led_pins_arr = hw_get_led_array();
    } else {
        led_pins_arr = hw_get_led_reversal_array();
    }

    //Adjust the color
    set_slot_light_color(color);
    pwm_sequ_val.channel_3 = 1; //Brightest
    pwm_sequ_val.channel_2 = 600;
    pwm_sequ_val.channel_1 = 880;
    pwm_sequ_val.channel_0 = 980; // The darkest
    while (1) {
        //Close all channels
        pwm_config.output_pins[0] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;

        setled = startled;
        if (setled < 3) { //During the positive period, only the first few LEDs can be on during 0, 1, 2
            //First determine that you can light a few lights
            leds2turnon = setled + 1; //1,2,3
            //Then set the PWM output channel
            for (i = 0; i < leds2turnon; i++) {
                pwm_config.output_pins[3 - i] = led_pins_arr[setled - i];
            }
        } else if (setled <= 7) { //During the positive period, it can light up 4 LEDs when it is greater than 4 less than 4
            // Set the PWM output channel
            for (i = 0; i < 4; i++) {
                pwm_config.output_pins[3 - i] = led_pins_arr[setled];
                setled--;
            }
        } else if (setled > 7 && setled <= 10) { // During the positive period, only a few LEDs can be lit at 8.9.10
            //First determine that you can light a few lights
            leds2turnon = 11 - setled;
            //Then set the PWM output channel
            for (i = 0; i < leds2turnon; i++) {
                pwm_config.output_pins[i] = led_pins_arr[setled - 3 + i];
            }

        } else { //During the positive period, reach 11
            //
        }
        //Process stop condition
        if (startled >= end) {
            //Calculation needs to hide a few lights
            leds2turnon = startled - end;
            //Hidden all those who go out
            for (i = 0; i < leds2turnon; i++) {
                pwm_config.output_pins[3 - i] = NRF_DRV_PWM_PIN_NOT_USED;
            }
            //Re -setting the specified position is the brightest
            if (end <= 7) {
                pwm_config.output_pins[3] = led_pins_arr[end];
            }

        }
        nrfx_pwm_uninit(&pwm0_ins);
        nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
        nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
        bsp_delay_ms(40);
        startled++;
        if (startled - end >= 4)break;
        if (startled > 11)break;
    }
}

//Switch card slot animation
//led_up The LED to be lit
//color_led_up The color of the lit LED 0-R,1-G,2-B
//led_down LED to be extinguished
//color_led_down The color of the LED to be extinguished 0-R,1-G,2-B
volatile bool callback_waiting = 0;
static void ledblink3_pwm_callback(nrfx_pwm_evt_type_t event_type) {
    if (event_type == NRF_DRV_PWM_EVT_FINISHED) {
        callback_waiting = 1;
    }
}
void ledblink3(uint8_t led_down, uint8_t color_led_down, uint8_t led_up, uint8_t color_led_up) {
    int16_t light_level = 99; //ledBrightnessValue
    uint32_t *led_pins = hw_get_led_array();
    if (led_down >= 0 && led_down <= 7) {
        //treatmentFirst
        pwm_config.output_pins[0] = led_pins[led_down];
        pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;
        while (light_level >= 0) {
            //processBrightness
            pwm_sequ_val.channel_0 = get_pwmduty(light_level);

            nrfx_pwm_uninit(&pwm0_ins); //turnOffPwmOutput

            if (led_up >= 0 && led_up <= 7) {
                nrf_gpio_pin_clear(led_pins[led_up]);
            }

            set_slot_light_color(color_led_down);

            nrf_drv_pwm_init(&pwm0_ins, &pwm_config, ledblink3_pwm_callback);
            nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);

            while (callback_waiting == 0); //Waiting for the output of the PWM module to complete
            bsp_delay_us(1234);
            callback_waiting = 0;
            light_level --;
        }
    }
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_clear(led_pins[i]);
    }
    if (led_up >= 0 && led_up <= 7) {
        //Treatment
        pwm_config.output_pins[0] = led_pins[led_up];
        pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;
        light_level  = 0;
        while (light_level < 99) {
            //Process brightness
            pwm_sequ_val.channel_0 = get_pwmduty(light_level);

            nrfx_pwm_uninit(&pwm0_ins); //Turn off PWM output

            if (led_down >= 0 && led_down <= 7) {
                nrf_gpio_pin_clear(led_pins[led_down]);
            }

            set_slot_light_color(color_led_up);

            nrf_drv_pwm_init(&pwm0_ins, &pwm_config, ledblink3_pwm_callback);
            nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);

            while (callback_waiting == 0); //Waiting for the output of the PWM module to complete
            bsp_delay_us(1234);
            callback_waiting = 0;
            light_level ++;
        }
    }
}

// 4 Light Tail horizontal movement cycle (not returning), does not include the disappearance of the tail, but includes the head of the head (for the type of playback type animation)
//dir 0-from 1 card slot to 8 card slot, 1-from 8 card slot to 1 card slot (Direction, the end point is determined by the END parameter)
//end To scan the number of lamps, decide the final animation area with the direction
//start_light stop_light 0-99 Indicate gradient brightness
void ledblink4(uint8_t color, uint8_t dir, uint8_t end, uint8_t start_light, uint8_t stop_light) {
    uint8_t startled = 0;
    uint8_t setled = 0;
    uint8_t leds2turnon = 0;
    uint8_t i = 0;
    uint32_t *led_pins_arr;
    volatile double light_cnd;
    //Processing direction
    if (dir == 0) {
        led_pins_arr = hw_get_led_array();
    } else {
        led_pins_arr = hw_get_led_reversal_array();
    }

    //Adjust the color
    set_slot_light_color(color);
    while (1) {
        //Set the brightness
        // The current brightness coefficient
        // Start reaches STOP through END times
        light_cnd = (((double)stop_light - (double)start_light) / end) * startled + start_light;
        pwm_sequ_val.channel_3 = get_pwmduty((uint8_t)(0.99 * light_cnd)); //1; //Brightest
        pwm_sequ_val.channel_2 = get_pwmduty((uint8_t)(0.60 * light_cnd)); //600;
        pwm_sequ_val.channel_1 = get_pwmduty((uint8_t)(0.30 * light_cnd)); //880;
        pwm_sequ_val.channel_0 = get_pwmduty((uint8_t)(0.01 * light_cnd)); // 980; // The darkest
        //Close all channels
        pwm_config.output_pins[0] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;

        setled = startled;
        if (setled < 3) { //During the positive period, only the first few LEDs can be on during 0, 1, 2
            //First determine that you can light a few lights
            leds2turnon = setled + 1; //1,2,3
            //Then set the PWM output channel
            for (i = 0; i < leds2turnon; i++) {
                pwm_config.output_pins[3 - i] = led_pins_arr[setled - i];
            }
        } else if (setled <= 7) { //During the positive period, it can light up 4 LEDs when it is greater than 4 less than 4
            //Set the PWM output channel
            for (i = 0; i < 4; i++) {
                pwm_config.output_pins[3 - i] = led_pins_arr[setled];
                setled--;
            }
        } else if (setled > 7 && setled <= 10) { // During the positive period, only a few LEDs can be lit at 8.9.10
            //First determine that you can light a few lights
            leds2turnon = 11 - setled;
            //Then set the PWM output channel
            for (i = 0; i < leds2turnon; i++) {
                pwm_config.output_pins[i] = led_pins_arr[setled - 3 + i];
            }

        } else { //During the positive period, reach 11
            //Nothing
        }
        //Process stop condition
        if (startled == end) {
            break;
        }
        nrfx_pwm_uninit(&pwm0_ins);
        nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
        nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
        bsp_delay_ms(50);
        startled++;
        if (startled - end >= 4)break;
        if (startled > 11)break;
    }
}

//Single light level movement
//color The color of the lit LED 0-R,1-G,2-B
//start Start the lamp position
//stop Stop lamp position
void ledblink5(uint8_t color, uint8_t start, uint8_t stop) {
    uint8_t setled = start;
    uint32_t *led_pins = hw_get_led_array();
    //Set the brightness
    pwm_sequ_val.channel_3 = 0;
    pwm_sequ_val.channel_2 = 0;
    pwm_sequ_val.channel_1 = 0;
    pwm_sequ_val.channel_0 = get_pwmduty(99);
    //Adjust the color
    set_slot_light_color(color);
    while (setled < (start < stop ? stop + 1 : stop - 1)) {
        //Close all channels
        pwm_config.output_pins[0] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;
        pwm_config.output_pins[0] = led_pins[setled];
        nrfx_pwm_uninit(&pwm0_ins);
        nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
        nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
        bsp_delay_ms(50);
        setled = start < stop ? setled + 1 : setled - 1;
    }
}


// Charging animation
// the current percentage of the battery 0-4 4 represents full electric breathing light
volatile bool callback_waiting6 = 0;
void ledblink6_pwm_callback(nrfx_pwm_evt_type_t event_type) {
    if (event_type == NRF_DRV_PWM_EVT_FINISHED) {
        callback_waiting6 = 1;
    }
}
void ledblink6(void) {
    uint32_t *led_array = hw_get_led_array();
    const uint16_t delay_time = 25;
    static int16_t light_level = 99; //LED brightness value

    if (!g_usb_led_marquee_enable && ledblink6_step != 0) {
        light_level = 99;
        callback_waiting6 = 0;
        rgb_marquee_stop();
        return;
    }

    if (ledblink6_step == 0) {
        set_slot_light_color(ledblink6_color);
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            nrf_gpio_pin_clear(led_array[i]);
        }
        pwm_config.output_pins[0] = led_array[2];
        pwm_config.output_pins[1] = led_array[3];
        pwm_config.output_pins[2] = led_array[4];
        pwm_config.output_pins[3] = led_array[5];
        ledblink6_step = 1;

        // Reset the state of the lamp when the USB is not turned on
        ledblink1_step = 0;
    }

    if (ledblink6_step == 1) {
        light_level  = 0;
        ledblink6_step = 2;
    }

    if (ledblink6_step == 2 || ledblink6_step == 3 || ledblink6_step == 4) {
        if (light_level <= 99) {
            if (ledblink6_step == 2) {
                //Treatment brightness
                pwm_sequ_val.channel_0 = get_pwmduty(light_level);
                pwm_sequ_val.channel_1 = pwm_sequ_val.channel_0;
                pwm_sequ_val.channel_2 = pwm_sequ_val.channel_0;
                pwm_sequ_val.channel_3 = pwm_sequ_val.channel_0;
                nrfx_pwm_uninit(&pwm0_ins); //Close PWM output
                set_slot_light_color(ledblink6_color);
                nrf_drv_pwm_init(&pwm0_ins, &pwm_config, ledblink6_pwm_callback);
                nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
                ledblink6_step = 3;
            }
            if (ledblink6_step == 3) {  //Waiting for the output of the PWM module to complete
                if (callback_waiting6 != 0) {
                    ledblink6_step = 4;
                    bsp_set_timer(timer, 0);
                }
            }
            if (ledblink6_step == 4) {
                if (!NO_TIMEOUT_1MS(timer, delay_time)) {
                    callback_waiting = 0;
                    light_level++;
                    ledblink6_step = 2;
                }
            }
        } else {
            ledblink6_step = 5;
        }
    }

    if (ledblink6_step == 5) {
        light_level = 99;
        ledblink6_step = 6;
    }

    if (ledblink6_step == 6 || ledblink6_step == 7 || ledblink6_step == 8) {
        if (light_level >= 0) {
            if (ledblink6_step == 6) {
                //Treatment brightness
                pwm_sequ_val.channel_0 = get_pwmduty(light_level);
                pwm_sequ_val.channel_1 = pwm_sequ_val.channel_0;
                pwm_sequ_val.channel_2 = pwm_sequ_val.channel_0;
                pwm_sequ_val.channel_3 = pwm_sequ_val.channel_0;
                nrfx_pwm_uninit(&pwm0_ins); //Close PWM output
                set_slot_light_color(ledblink6_color);
                nrf_drv_pwm_init(&pwm0_ins, &pwm_config, ledblink6_pwm_callback);
                nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
                ledblink6_step = 7;
            }
            if (ledblink6_step == 7) {  //Waiting for the output of the PWM module to complete
                if (callback_waiting6 != 0) {
                    ledblink6_step = 8;
                    bsp_set_timer(timer, 0);
                }
            }
            if (ledblink6_step == 8) {
                if (!NO_TIMEOUT_1MS(timer, delay_time)) {
                    callback_waiting = 0;
                    light_level--;
                    ledblink6_step = 6;
                }
            }
        } else {
            ledblink6_step = 0;
            //if (++ledblink6_color == RGB_WHITE) ledblink6_color = RGB_RED;
            uint8_t new_color = rand() % 6;
            for (; new_color == ledblink6_color; new_color = rand() % 6);
            ledblink6_color = new_color;
        }
    }
}

/**
 * @brief Whether the current lighting effect enables
 *
 * @return true Make the state, flickering in the lighting effect
 * @return false The state is prohibited, in the state of ordinary card slot indicator
 */
bool is_rgb_marquee_enable(void) {
    return g_usb_led_marquee_enable;
}

// External functions from rfid_main.c and tag_emulation.c
extern uint8_t tag_emulation_get_slot(void);
extern uint8_t get_color_by_slot(uint8_t slot);

/**
 * @brief Get the basic color enum from slot color index
 */
static uint8_t slot_color_to_enum(uint8_t slot_color) {
    // slot_color: 0=R (dual freq), 1=G (HF), 2=B (LF)
    switch (slot_color) {
        case 0: return RGB_RED;
        case 1: return RGB_GREEN;
        case 2: return RGB_BLUE;
        default: return RGB_GREEN;
    }
}

/**
 * @brief RGB bootup animation - rainbow spiral converging to slot with PWM fading
 */
void rgb_bootup_animation(void) {
    uint32_t *led_pins = hw_get_led_array();
    uint8_t slot = tag_emulation_get_slot();
    uint8_t slot_color = get_color_by_slot(slot);
    
    // Clear all LEDs first
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_clear(led_pins[i]);
    }
    
    // Phase 1: Rainbow wave - quick sweep left to right
    for (uint8_t wave = 0; wave < 2; wave++) {
        for (uint8_t pos = 0; pos < RGB_LIST_NUM + 4; pos++) {
            // Clear previous LEDs
            for (uint8_t j = 0; j < RGB_LIST_NUM; j++) {
                nrf_gpio_pin_clear(led_pins[j]);
            }
            
            // 4-LED trail with different colors
            for (uint8_t t = 0; t < 4; t++) {
                int8_t led_pos = pos - t;
                if (led_pos >= 0 && led_pos < RGB_LIST_NUM) {
                    // Cycle through R, G, B, Y, C, M
                    uint8_t color = ((pos + wave * 2 + t) % 6);
                    set_slot_light_color(color);
                    nrf_gpio_pin_set(led_pins[led_pos]);
                }
            }
            bsp_delay_ms(30);
        }
    }
    
    // Phase 2: All LEDs flash rainbow colors
    for (uint8_t c = 0; c < 6; c++) {
        set_slot_light_color(c);
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            nrf_gpio_pin_set(led_pins[i]);
        }
        bsp_delay_ms(50);
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            nrf_gpio_pin_clear(led_pins[i]);
        }
        bsp_delay_ms(25);
    }
    
    // Phase 3: Converge to slot
    set_slot_light_color(slot_color_to_enum(slot_color));
    
    // Light all, then turn off from edges toward slot
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_set(led_pins[i]);
    }
    bsp_delay_ms(100);
    
    for (uint8_t dist = 7; dist > 0; dist--) {
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            uint8_t d = (i > slot) ? (i - slot) : (slot - i);
            if (d >= dist) {
                nrf_gpio_pin_clear(led_pins[i]);
            }
        }
        bsp_delay_ms(40);
    }
    
    // Final: only slot LED on
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        if (i != slot) nrf_gpio_pin_clear(led_pins[i]);
    }
    nrf_gpio_pin_set(led_pins[slot]);
}

/**
 * @brief Shutdown animation - fade out from slot
 */
void rgb_shutdown_animation(void) {
    uint32_t *led_pins = hw_get_led_array();
    uint8_t slot = tag_emulation_get_slot();
    uint8_t slot_color = get_color_by_slot(slot);
    
    set_slot_light_color(slot_color_to_enum(slot_color));
    
    // Clear all first
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_clear(led_pins[i]);
    }
    
    // Light slot LED
    nrf_gpio_pin_set(led_pins[slot]);
    bsp_delay_ms(100);
    
    // Expand from slot outward
    for (uint8_t radius = 1; radius <= 7; radius++) {
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            uint8_t d = (i > slot) ? (i - slot) : (slot - i);
            if (d <= radius) {
                nrf_gpio_pin_set(led_pins[i]);
            }
        }
        bsp_delay_ms(35);
    }
    
    bsp_delay_ms(150);
    
    // Contract back
    for (uint8_t radius = 7; radius > 0; radius--) {
        for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
            uint8_t d = (i > slot) ? (i - slot) : (slot - i);
            if (d >= radius) {
                nrf_gpio_pin_clear(led_pins[i]);
            }
        }
        bsp_delay_ms(30);
    }
    
    // Fade slot LED using PWM
    pwm_config.output_pins[0] = led_pins[slot];
    pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
    pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
    pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;
    
    for (int8_t b = 99; b >= 0; b -= 5) {
        pwm_sequ_val.channel_0 = get_pwmduty(b);
        nrfx_pwm_uninit(&pwm0_ins);
        nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
        nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
        bsp_delay_ms(20);
    }
    
    // All off
    nrfx_pwm_uninit(&pwm0_ins);
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_clear(led_pins[i]);
    }
}

/**
 * @brief Flash slot indicator - uses existing slot
 */
void rgb_flash_slot_indicator(uint8_t slot, uint8_t color) {
    uint32_t *led_pins = hw_get_led_array();
    
    set_slot_light_color(slot_color_to_enum(color));
    
    for (uint8_t i = 0; i < 3; i++) {
        nrf_gpio_pin_set(led_pins[slot]);
        bsp_delay_ms(100);
        nrf_gpio_pin_clear(led_pins[slot]);
        bsp_delay_ms(80);
    }
    nrf_gpio_pin_set(led_pins[slot]);
}

/**
 * @brief Set slot info - now just a stub since we use existing functions
 */
void rgb_set_slot_info(uint8_t slot, uint8_t color) {
    // Not needed - we use tag_emulation_get_slot() and get_color_by_slot()
    (void)slot;
    (void)color;
}

/**
 * @brief Non-blocking idle animation with smooth PWM rainbow colors
 * Polls slot actively to keep slot LED always lit and stable
 * Uses PWM for smooth 256+ color gradients
 */
bool rgb_idle_cycle_step(void) {
    static uint32_t last_update = 0;
    static uint16_t hue = 0;          // 0-1535 for smooth rainbow (256 * 6 = 1536 steps)
    static uint8_t anim_led = 0;      // Current LED being animated
    static uint8_t pwm_initialized = 0;
    
    uint32_t now = app_timer_cnt_get();
    
    // 50ms update rate for smooth animation
    if (app_timer_cnt_diff_compute(now, last_update) < APP_TIMER_TICKS(50)) {
        return false;
    }
    last_update = now;
    
    uint32_t *led_pins = hw_get_led_array();
    
    // ACTIVELY POLL current slot - this ensures slot is always correct
    uint8_t slot = tag_emulation_get_slot();
    uint8_t slot_color = get_color_by_slot(slot);
    
    // Advance rainbow hue
    hue = (hue + 8) % 1536;
    
    // Move to next non-slot LED for animation
    do {
        anim_led = (anim_led + 1) % RGB_LIST_NUM;
    } while (anim_led == slot);
    
    // Convert hue (0-1535) to RGB PWM values for smooth rainbow
    // PWM values are inverted: 0=full bright, 1000=off
    uint16_t r, g, b;
    uint16_t sector = hue / 256;
    uint16_t offset = hue % 256;
    
    switch (sector) {
        case 0:  // Red -> Yellow
            r = 0;
            g = 1000 - (offset * 1000 / 255);
            b = 1000;
            break;
        case 1:  // Yellow -> Green
            r = (offset * 1000 / 255);
            g = 0;
            b = 1000;
            break;
        case 2:  // Green -> Cyan
            r = 1000;
            g = 0;
            b = 1000 - (offset * 1000 / 255);
            break;
        case 3:  // Cyan -> Blue
            r = 1000;
            g = (offset * 1000 / 255);
            b = 0;
            break;
        case 4:  // Blue -> Magenta
            r = 1000 - (offset * 1000 / 255);
            g = 1000;
            b = 0;
            break;
        default:  // Magenta -> Red
            r = 0;
            g = 1000;
            b = (offset * 1000 / 255);
            break;
    }
    
    // Turn OFF all LEDs except slot LED (using GPIO, not PWM for off state)
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        if (i != slot && i != anim_led) {
            nrf_gpio_pin_clear(led_pins[i]);
        }
    }
    
    // Set slot LED color and keep it ON (stable, always visible)
    set_slot_light_color(slot_color_to_enum(slot_color));
    nrf_gpio_pin_set(led_pins[slot]);
    
    // Configure PWM for the animated LED with rainbow color
    // Use all 4 PWM channels: 3 for RGB color, 1 for the animated LED
    pwm_sequ_val.channel_0 = r;    // Red component
    pwm_sequ_val.channel_1 = g;    // Green component  
    pwm_sequ_val.channel_2 = b;    // Blue component
    pwm_sequ_val.channel_3 = 0;    // LED brightness (0 = full on)
    
    // Configure PWM output pin for animated LED
    pwm_config.output_pins[0] = led_pins[anim_led];
    pwm_config.output_pins[1] = NRF_DRV_PWM_PIN_NOT_USED;
    pwm_config.output_pins[2] = NRF_DRV_PWM_PIN_NOT_USED;
    pwm_config.output_pins[3] = NRF_DRV_PWM_PIN_NOT_USED;
    
    // Reinit PWM with new pin config
    if (pwm_initialized) {
        nrfx_pwm_uninit(&pwm0_ins);
    }
    nrf_drv_pwm_init(&pwm0_ins, &pwm_config, NULL);
    nrf_drv_pwm_simple_playback(&pwm0_ins, &seq, 1, NRF_DRV_PWM_FLAG_LOOP);
    pwm_initialized = 1;
    
    return true;
}

/**
 * @brief Reset idle cycle and turn off all LEDs
 */
void rgb_idle_cycle_reset(void) {
    nrfx_pwm_stop(&pwm0_ins, true);
    nrfx_pwm_uninit(&pwm0_ins);
    uint32_t *led_pins = hw_get_led_array();
    for (uint8_t i = 0; i < RGB_LIST_NUM; i++) {
        nrf_gpio_pin_clear(led_pins[i]);
    }
}

