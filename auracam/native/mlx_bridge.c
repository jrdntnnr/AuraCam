#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"

void auracam_mlx_i2c_set_device(const char *device);
void auracam_mlx_i2c_close(void);
const char *auracam_mlx_i2c_error(void);

static paramsMLX90640 params;
static uint16_t frame_data[834];
static float temperatures[768];
static float image_values[768];
static uint8_t current_address = 0x33;
static unsigned seen_subpages = 0;
static char bridge_error[320] = "not initialized";
static int initialized = 0;

static int fail(const char *stage, int code) {
    snprintf(bridge_error, sizeof(bridge_error), "%s failed (%d): %s",
             stage, code, auracam_mlx_i2c_error());
    return code ? code : -1;
}

const char *auracam_mlx_error(void) { return bridge_error; }

int auracam_mlx_init(const char *device, uint8_t address, int refresh_code) {
    uint16_t ee_data[832];
    int result;
    int warning = 0;
    auracam_mlx_i2c_set_device(device);
    current_address = address;
    MLX90640_I2CInit();
    result = MLX90640_DumpEE(current_address, ee_data);
    if (result != MLX90640_NO_ERROR) {
        return fail("EEPROM read", result);
    }
    memset(&params, 0, sizeof(params));
    result = MLX90640_ExtractParameters(ee_data, &params);
    if (result <= -MLX90640_EEPROM_DATA_ERROR) {
        return fail("parameter extraction", result);
    }
    if (result < 0) {
        warning = result;
    }
    result = MLX90640_SetChessMode(current_address);
    if (result != MLX90640_NO_ERROR) {
        return fail("set chess mode", result);
    }
    result = MLX90640_SetRefreshRate(current_address, (uint8_t)refresh_code);
    if (result != MLX90640_NO_ERROR) {
        return fail("set refresh rate", result);
    }
    memset(frame_data, 0, sizeof(frame_data));
    memset(temperatures, 0, sizeof(temperatures));
    memset(image_values, 0, sizeof(image_values));
    seen_subpages = 0;
    initialized = 1;
    if (warning) {
        snprintf(bridge_error, sizeof(bridge_error),
                 "initialized with bad-pixel warning %d", warning);
    } else {
        snprintf(bridge_error, sizeof(bridge_error), "ok");
    }
    return warning;
}

int auracam_mlx_set_refresh(int refresh_code) {
    int result;
    if (!initialized) {
        return fail("set refresh rate before init", -1);
    }
    result = MLX90640_SetRefreshRate(current_address, (uint8_t)refresh_code);
    if (result != MLX90640_NO_ERROR) {
        return fail("set refresh rate", result);
    }
    return result;
}

int auracam_mlx_read(float emissivity, float reflected_offset,
                     float *out_temperatures, float *out_image,
                     float *ambient, float *vdd, int *subpage, int *complete) {
    int result;
    int page;
    float ta;
    if (!initialized) {
        return fail("read before init", -1);
    }
    result = MLX90640_GetFrameData(current_address, frame_data);
    if (result < MLX90640_NO_ERROR) {
        return fail("frame read", result);
    }
    page = MLX90640_GetSubPageNumber(frame_data);
    ta = MLX90640_GetTa(frame_data, &params);
    MLX90640_CalculateTo(frame_data, &params, emissivity, ta - reflected_offset,
                         temperatures);
    MLX90640_GetImage(frame_data, &params, image_values);
    MLX90640_BadPixelsCorrection(params.brokenPixels, temperatures, 1, &params);
    MLX90640_BadPixelsCorrection(params.outlierPixels, temperatures, 1, &params);
    MLX90640_BadPixelsCorrection(params.brokenPixels, image_values, 1, &params);
    MLX90640_BadPixelsCorrection(params.outlierPixels, image_values, 1, &params);
    seen_subpages |= 1u << (unsigned)(page & 1);
    memcpy(out_temperatures, temperatures, sizeof(temperatures));
    memcpy(out_image, image_values, sizeof(image_values));
    *ambient = ta;
    *vdd = MLX90640_GetVdd(frame_data, &params);
    *subpage = page;
    *complete = seen_subpages == 3;
    return MLX90640_NO_ERROR;
}

int auracam_mlx_mode(void) {
    return initialized ? MLX90640_GetCurMode(current_address) : -1;
}

int auracam_mlx_refresh(void) {
    return initialized ? MLX90640_GetRefreshRate(current_address) : -1;
}

void auracam_mlx_close(void) {
    auracam_mlx_i2c_close();
    initialized = 0;
}
