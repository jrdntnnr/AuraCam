#include "lvgl.h"
#include "src/drivers/display/fb/lv_linux_fbdev.h"
#include <array>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/input.h>
#include <string>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <unistd.h>

constexpr int kWidth = 192;
constexpr int kHeight = 144;
constexpr int kTextBytes = 512;
constexpr int kPixelBytes = kWidth * kHeight * 4;
constexpr int kHoldMs = 700;
volatile sig_atomic_t running = 1;

uint32_t ticks() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

void stop(int) {
    running = 0;
}

int keyboard() {
    for (int index = 0; index < 32; ++index) {
        const auto path = "/dev/input/event" + std::to_string(index);
        int fd = open(path.c_str(), O_RDONLY | O_NONBLOCK);
        if (fd < 0) {
            continue;
        }
        char name[128]{};
        ioctl(fd, EVIOCGNAME(sizeof(name)), name);
        if (strstr(name, "tca8418")) {
            return fd;
        }
        close(fd);
    }
    return -1;
}

int main() {
    signal(SIGPIPE, SIG_IGN);
    signal(SIGTERM, stop);
    signal(SIGINT, stop);
    int keys = keyboard();
    if (keys < 0) {
        fprintf(stderr, "Cardputer keyboard not found\n");
        return 1;
    }
    int commands[2], frames[2];
    if (pipe(commands) || pipe(frames)) {
        return 1;
    }
    pid_t child = fork();
    if (child < 0) {
        return 1;
    }
    if (child == 0) {
        dup2(commands[0], STDIN_FILENO);
        dup2(frames[1], STDOUT_FILENO);
        close(commands[0]);
        close(commands[1]);
        close(frames[0]);
        close(frames[1]);
        close(keys);
        execlp("python3", "python3", "-m", "auracam.cardputer", nullptr);
        _exit(127);
    }
    close(commands[0]);
    close(frames[1]);
    fcntl(frames[0], F_SETFL, O_NONBLOCK);
    lv_init();
    lv_tick_set_cb(ticks);
    auto* display = lv_linux_fbdev_create();
    lv_linux_fbdev_set_file(display, "/dev/fb_lcd");
    auto* screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x080e0c), 0);
    lv_obj_set_style_text_color(screen, lv_color_hex(0x7fe6ad), 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    auto* image = lv_image_create(screen);
    lv_obj_set_pos(image, 0, 0);
    auto* info = lv_label_create(screen);
    lv_obj_set_pos(info, 196, 2);
    lv_obj_set_size(info, 122, 140);
    lv_label_set_text(info, "Starting AuraCam...");
    std::array<lv_obj_t*, 5> labels{};
    for (int i = 0; i < 5; ++i) {
        labels[i] = lv_label_create(screen);
        lv_obj_set_pos(labels[i], i * 64, 149);
        lv_obj_set_width(labels[i], 64);
        lv_obj_set_style_text_align(labels[i], LV_TEXT_ALIGN_CENTER, 0);
    }
    std::array<unsigned char, kPixelBytes> pixels{};
    lv_image_dsc_t descriptor{};
    descriptor.header.magic = LV_IMAGE_HEADER_MAGIC;
    descriptor.header.cf = LV_COLOR_FORMAT_ARGB8888;
    descriptor.header.w = kWidth;
    descriptor.header.h = kHeight;
    descriptor.header.stride = kWidth * 4;
    descriptor.data_size = pixels.size();
    descriptor.data = pixels.data();
    std::array<unsigned char, kTextBytes + kPixelBytes> packet{};
    size_t received = 0;
    uint32_t escape_at = 0;
    while (running) {
        input_event event{};
        while (read(keys, &event, sizeof(event)) == sizeof(event)) {
            if (event.type != EV_KEY) {
                continue;
            }
            if (event.code == KEY_ESC) {
                if (event.value == 1) {
                    escape_at = ticks();
                } else if (event.value == 0) {
                    escape_at = 0;
                }
            }
            if (event.value == 1 && event.code >= KEY_4 && event.code <= KEY_8) {
                const char command = '4' + event.code - KEY_4;
                if (write(commands[1], &command, 1) != 1) {
                    running = 0;
                }
            }
        }
        if (escape_at && ticks() - escape_at >= kHoldMs) {
            running = 0;
        }
        ssize_t count = read(frames[0], packet.data() + received, packet.size() - received);
        if (count == 0) {
            running = 0;
        } else if (count > 0) {
            received += count;
        }
        if (received == packet.size()) {
            packet[kTextBytes - 1] = 0;
            std::string text(reinterpret_cast<char*>(packet.data()));
            const auto split = text.find('\t');
            lv_label_set_text(info, text.substr(0, split).c_str());
            std::string actions = split == std::string::npos ? "Menu|Snap|Record|Source|Mode" : text.substr(split + 1);
            for (int i = 0; i < 5; ++i) {
                const auto separator = actions.find('|');
                lv_label_set_text(labels[i], actions.substr(0, separator).c_str());
                actions = separator == std::string::npos ? "" : actions.substr(separator + 1);
            }
            memcpy(pixels.data(), packet.data() + kTextBytes, pixels.size());
            lv_image_set_src(image, &descriptor);
            lv_obj_invalidate(image);
            received = 0;
        }
        lv_timer_handler();
        usleep(5000);
    }
    const char quit = 'q';
    write(commands[1], &quit, 1);
    close(commands[1]);
    close(frames[0]);
    close(keys);
    waitpid(child, nullptr, 0);
    lv_deinit();
    return 0;
}
