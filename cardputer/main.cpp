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

LV_FONT_DECLARE(share_tech_mono_12);
LV_FONT_DECLARE(share_tech_mono_20);

constexpr int kScreenWidth = 320;
constexpr int kScreenHeight = 170;
constexpr int kWidth = 192;
constexpr int kHeight = 144;
constexpr int kTextBytes = 512;
constexpr int kPixelBytes = kWidth * kHeight * 4;
constexpr int kHoldMs = 700;
constexpr int kActionCount = 5;
constexpr int kActionWidth = kScreenWidth / kActionCount;
constexpr int kActionBarY = kHeight + 5;
constexpr int kScanBarWidth = 200;
constexpr int kScanBarHeight = 4;
constexpr int kScanPeriodMs = 1600;
constexpr uint32_t kBackground = 0x080e0c;
constexpr uint32_t kPhosphor = 0x7fe6ad;
constexpr uint32_t kPhosphorDim = 0x2a5a40;

volatile sig_atomic_t running = 1;

enum class Phase { Loading, Live };

struct Ui {
    lv_obj_t* loading;
    lv_obj_t* loading_status;
    lv_obj_t* image;
    lv_obj_t* info;
    std::array<lv_obj_t*, kActionCount> actions;
    Phase phase;
};

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

lv_obj_t* label(lv_obj_t* parent, const lv_font_t* font, lv_text_align_t align) {
    auto* object = lv_label_create(parent);
    lv_obj_set_style_text_font(object, font, 0);
    lv_obj_set_style_text_color(object, lv_color_hex(kPhosphor), 0);
    lv_obj_set_style_text_align(object, align, 0);
    lv_label_set_text(object, "");
    return object;
}

void scan_step(void* bar, int32_t value) {
    lv_bar_set_value(static_cast<lv_obj_t*>(bar), value, LV_ANIM_OFF);
}

lv_obj_t* scan_bar(lv_obj_t* parent) {
    auto* bar = lv_bar_create(parent);
    lv_obj_set_size(bar, kScanBarWidth, kScanBarHeight);
    lv_obj_align(bar, LV_ALIGN_CENTER, 0, 12);
    lv_bar_set_range(bar, 0, 100);
    lv_obj_set_style_bg_color(bar, lv_color_hex(kPhosphorDim), LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar, lv_color_hex(kPhosphor), LV_PART_INDICATOR);
    lv_obj_set_style_radius(bar, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(bar, 0, LV_PART_INDICATOR);

    lv_anim_t animation;
    lv_anim_init(&animation);
    lv_anim_set_var(&animation, bar);
    lv_anim_set_values(&animation, 0, 100);
    lv_anim_set_duration(&animation, kScanPeriodMs);
    lv_anim_set_playback_duration(&animation, kScanPeriodMs);
    lv_anim_set_repeat_count(&animation, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_exec_cb(&animation, scan_step);
    lv_anim_start(&animation);
    return bar;
}

Ui build_ui() {
    auto* screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(kBackground), 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    Ui ui{};
    ui.phase = Phase::Loading;

    ui.loading = lv_obj_create(screen);
    lv_obj_set_size(ui.loading, kScreenWidth, kScreenHeight);
    lv_obj_set_pos(ui.loading, 0, 0);
    lv_obj_set_style_bg_color(ui.loading, lv_color_hex(kBackground), 0);
    lv_obj_set_style_border_width(ui.loading, 0, 0);
    lv_obj_set_style_radius(ui.loading, 0, 0);
    lv_obj_set_style_pad_all(ui.loading, 0, 0);
    lv_obj_remove_flag(ui.loading, LV_OBJ_FLAG_SCROLLABLE);

    auto* title = label(ui.loading, &share_tech_mono_20, LV_TEXT_ALIGN_CENTER);
    lv_label_set_text(title, "AURACAM");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 34);

    auto* subtitle = label(ui.loading, &share_tech_mono_12, LV_TEXT_ALIGN_CENTER);
    lv_label_set_text(subtitle, "RGB / UV + MLX90640 THERMAL FUSION");
    lv_obj_set_style_text_color(subtitle, lv_color_hex(kPhosphorDim), 0);
    lv_obj_align(subtitle, LV_ALIGN_TOP_MID, 0, 60);

    scan_bar(ui.loading);

    ui.loading_status = label(ui.loading, &share_tech_mono_12, LV_TEXT_ALIGN_CENTER);
    lv_obj_set_width(ui.loading_status, kScreenWidth - 16);
    lv_obj_align(ui.loading_status, LV_ALIGN_BOTTOM_MID, 0, -28);
    lv_label_set_text(ui.loading_status, "INITIALIZING");

    auto* footer = label(ui.loading, &share_tech_mono_12, LV_TEXT_ALIGN_CENTER);
    lv_label_set_text(footer, "HOLD ESC TO EXIT");
    lv_obj_set_style_text_color(footer, lv_color_hex(kPhosphorDim), 0);
    lv_obj_align(footer, LV_ALIGN_BOTTOM_MID, 0, -6);

    ui.image = lv_image_create(screen);
    lv_obj_set_pos(ui.image, 0, 0);
    lv_obj_add_flag(ui.image, LV_OBJ_FLAG_HIDDEN);

    ui.info = label(screen, &share_tech_mono_12, LV_TEXT_ALIGN_LEFT);
    lv_obj_set_pos(ui.info, kWidth + 4, 2);
    lv_obj_set_size(ui.info, kScreenWidth - kWidth - 6, kHeight - 4);
    lv_obj_add_flag(ui.info, LV_OBJ_FLAG_HIDDEN);

    for (int i = 0; i < kActionCount; ++i) {
        ui.actions[i] = label(screen, &share_tech_mono_12, LV_TEXT_ALIGN_CENTER);
        lv_obj_set_pos(ui.actions[i], i * kActionWidth, kActionBarY);
        lv_obj_set_width(ui.actions[i], kActionWidth);
        lv_obj_add_flag(ui.actions[i], LV_OBJ_FLAG_HIDDEN);
    }
    return ui;
}

void show_phase(Ui& ui, Phase phase) {
    if (ui.phase == phase) {
        return;
    }
    ui.phase = phase;
    const bool live = phase == Phase::Live;
    lv_obj_set_flag(ui.loading, LV_OBJ_FLAG_HIDDEN, live);
    lv_obj_set_flag(ui.image, LV_OBJ_FLAG_HIDDEN, !live);
    lv_obj_set_flag(ui.info, LV_OBJ_FLAG_HIDDEN, !live);
    for (auto* action : ui.actions) {
        lv_obj_set_flag(action, LV_OBJ_FLAG_HIDDEN, !live);
    }
}

void apply_packet(Ui& ui, const std::string& text, lv_image_dsc_t& descriptor) {
    const auto split = text.find('\t');
    const std::string lines = text.substr(0, split);
    std::string actions = split == std::string::npos ? "" : text.substr(split + 1);
    if (actions.empty()) {
        show_phase(ui, Phase::Loading);
        lv_label_set_text(ui.loading_status, lines.c_str());
        return;
    }
    show_phase(ui, Phase::Live);
    lv_label_set_text(ui.info, lines.c_str());
    for (auto* action : ui.actions) {
        const auto separator = actions.find('|');
        lv_label_set_text(action, actions.substr(0, separator).c_str());
        actions = separator == std::string::npos ? "" : actions.substr(separator + 1);
    }
    lv_image_set_src(ui.image, &descriptor);
    lv_obj_invalidate(ui.image);
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
    Ui ui = build_ui();

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
            memcpy(pixels.data(), packet.data() + kTextBytes, pixels.size());
            apply_packet(ui, std::string(reinterpret_cast<char*>(packet.data())), descriptor);
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
