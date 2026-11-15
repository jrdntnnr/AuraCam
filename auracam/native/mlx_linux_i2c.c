#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"

static int mlx_fd = -1;
static char mlx_device[128] = "/dev/i2c-1";
static char mlx_error[256] = "not initialized";

static void set_error(const char *operation) {
    snprintf(mlx_error, sizeof(mlx_error), "%s: %s", operation, strerror(errno));
}

void auracam_mlx_i2c_set_device(const char *device) {
    if (device && *device) {
        snprintf(mlx_device, sizeof(mlx_device), "%s", device);
    }
}

const char *auracam_mlx_i2c_error(void) { return mlx_error; }

void auracam_mlx_i2c_close(void) {
    if (mlx_fd >= 0) {
        close(mlx_fd);
        mlx_fd = -1;
    }
}

void MLX90640_I2CInit(void) {
    if (mlx_fd >= 0) {
        return;
    }
    mlx_fd = open(mlx_device, O_RDWR | O_CLOEXEC);
    if (mlx_fd < 0) {
        set_error("open I2C bus");
    } else {
        snprintf(mlx_error, sizeof(mlx_error), "ok");
    }
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t words, uint16_t *data) {
    uint8_t address[2] = {(uint8_t)(startAddress >> 8), (uint8_t)startAddress};
    size_t byte_count = (size_t)words * 2;
    uint8_t *raw = malloc(byte_count);
    struct i2c_msg messages[2];
    struct i2c_rdwr_ioctl_data request;
    int result;

    if (!raw) {
        errno = ENOMEM;
        set_error("allocate I2C read buffer");
        return -MLX90640_I2C_NACK_ERROR;
    }
    MLX90640_I2CInit();
    if (mlx_fd < 0) {
        free(raw);
        return -MLX90640_I2C_NACK_ERROR;
    }
    messages[0] = (struct i2c_msg){.addr = slaveAddr, .flags = 0, .len = 2, .buf = address};
    messages[1] = (struct i2c_msg){.addr = slaveAddr, .flags = I2C_M_RD,
                                   .len = (uint16_t)byte_count, .buf = raw};
    request = (struct i2c_rdwr_ioctl_data){.msgs = messages, .nmsgs = 2};
    result = ioctl(mlx_fd, I2C_RDWR, &request);
    if (result < 0) {
        set_error("I2C register read");
        free(raw);
        return -MLX90640_I2C_NACK_ERROR;
    }
    for (uint16_t i = 0; i < words; ++i) {
        data[i] = ((uint16_t)raw[i * 2] << 8) | raw[i * 2 + 1];
    }
    free(raw);
    return MLX90640_NO_ERROR;
}

int MLX90640_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data) {
    uint8_t raw[4] = {(uint8_t)(writeAddress >> 8), (uint8_t)writeAddress,
                      (uint8_t)(data >> 8), (uint8_t)data};
    struct i2c_msg message = {.addr = slaveAddr, .flags = 0, .len = 4, .buf = raw};
    struct i2c_rdwr_ioctl_data request = {.msgs = &message, .nmsgs = 1};
    MLX90640_I2CInit();
    if (mlx_fd < 0) {
        return -MLX90640_I2C_WRITE_ERROR;
    }
    if (ioctl(mlx_fd, I2C_RDWR, &request) < 0) {
        set_error("I2C register write");
        return -MLX90640_I2C_WRITE_ERROR;
    }
    return MLX90640_NO_ERROR;
}

int MLX90640_I2CGeneralReset(void) {
    uint8_t reset = 0x06;
    struct i2c_msg message = {.addr = 0x00, .flags = 0, .len = 1, .buf = &reset};
    struct i2c_rdwr_ioctl_data request = {.msgs = &message, .nmsgs = 1};
    MLX90640_I2CInit();
    if (mlx_fd < 0 || ioctl(mlx_fd, I2C_RDWR, &request) < 0) {
        set_error("I2C general reset");
        return -MLX90640_I2C_WRITE_ERROR;
    }
    return MLX90640_NO_ERROR;
}

void MLX90640_I2CFreqSet(int freq) { (void)freq; }
