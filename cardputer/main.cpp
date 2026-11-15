/*
 * AuraCam frontend for the Cardputer Zero's 320x170 panel.
 *
 * Forks the Python bridge (auracam/cardputer.py), reads fixed-size packets
 * from it and draws them with LVGL; keys 4-8 go back to it on stdin.
 *
 *   +--------------------------------------------------------------+
 *   | AURACAM                                            REC 00:12 |
 *   |--------------------------------------------------------------|
 *   | RGB 15   | +------------------------------+ |       P 24.1C |
 *   | IR  16   | |                              | |       H 33.0C |
 *   |          | |     192x144 preview with     | |       L 19.2C |
 *   | THRESHOLD| |     P/H/L markers            | |               |
 *   | 26.0C    | |                              | |               |
 *   |          | +------------------------------+ |               |
 *   |--------------------------------------------------------------|
 *   |  MENU      SNAP      RECORD      HUD      MODE               |
 *   +--------------------------------------------------------------+
 *
 * While starting, the same header sits over a terminal boot log whose
 * running steps show a rotating | / - \ cursor.
 */
#include "lvgl.h"
#include "src/drivers/display/fb/lv_linux_fbdev.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <linux/input.h>
#include <string>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

LV_FONT_DECLARE(aura_pixel_7);

// Panel and packet geometry (must match auracam/cardputer.py).
constexpr int kScreenWidth = 320;
constexpr int kScreenHeight = 170;
constexpr int kWidth = 192;
constexpr int kHeight = 144;
constexpr int kTextBytes = 1024;
constexpr int kPixelBytes = kWidth * kHeight * 4;

// Layout.
constexpr int kMargin = 2;
constexpr int kHeaderRuleY = 11;
constexpr int kPreviewX = (kScreenWidth - kWidth) / 2;
constexpr int kPreviewY = 13;
constexpr int kSideWidth = kPreviewX - 2 * kMargin;
constexpr int kSideY = kPreviewY + 1;
constexpr int kFooterRuleY = kPreviewY + kHeight + 1;
constexpr int kFooterY = kFooterRuleY + 2;
constexpr int kActionCount = 5;
constexpr int kActionWidth = kScreenWidth / kActionCount;
constexpr int kLogY = kPreviewY + 2;
constexpr size_t kLeaderColumn = 16;
constexpr int kToastWidth = 120;
constexpr int kToastHeight = 22;
constexpr int kToastBarHeight = 2;
constexpr int kToastPad = 4;

// Timing.
constexpr uint32_t kQuitHoldMs = 3000;
constexpr uint32_t kSpinnerMs = 110;
constexpr uint32_t kCursorMs = 500;
constexpr useconds_t kLoopSleepUs = 5000;

// Colours: the bridge sends the HUD palette; dim text is a mix toward black.
constexpr uint32_t kBackground = 0x000000;
constexpr uint32_t kDefaultColor = 0xffc200;
constexpr lv_opa_t kDimMix = LV_OPA_40;

constexpr char kSpinner[] = {'|', '/', '-', '\\'};

// Arrow keys go to the bridge as U/D/L/R (calibration). The Cardputer
// prints its arrows on F (up), Z (left), X (down) and C (right).
struct Arrow {
    int code;
    char command;
};
constexpr Arrow kArrows[] = {
    {KEY_F, 'U'}, {KEY_Z, 'L'}, {KEY_X, 'D'}, {KEY_C, 'R'},
    {KEY_UP, 'U'}, {KEY_LEFT, 'L'}, {KEY_DOWN, 'D'}, {KEY_RIGHT, 'R'},
};
constexpr int kKeyPress = 1;
constexpr int kKeyRepeat = 2;
constexpr char kFieldSeparator = '\t';
constexpr char kStateSeparator = '|';
constexpr char kStateRunning[] = "RUN";

volatile sig_atomic_t running = 1;

enum class Phase { Boot, Live };

// Packet fields, in order.
enum Field { kKind, kColor, kHeader, kBody, kRight, kActions, kFooter, kFieldCount };

struct Step {
    std::string label;
    std::string state;
};

struct Ui {
    lv_style_t text;
    lv_style_t dim;
    lv_style_t rule;
    lv_style_t toast;
    lv_style_t fill;
    uint32_t color;
    lv_obj_t* title;
    lv_obj_t* status;
    lv_obj_t* log;
    lv_obj_t* footer;
    lv_obj_t* image;
    lv_obj_t* left;
    lv_obj_t* right;
    std::array<lv_obj_t*, kActionCount> actions;
    lv_obj_t* toast_box;
    lv_obj_t* toast_bar;
    std::vector<Step> steps;
    Phase phase;
    uint32_t tick;
    bool cursor;
};

uint32_t ticks() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

void stop(int) {
    running = 0;
}

// Command for a key event, or 0. Arrows also repeat while held.
char command_for(const input_event& event) {
    if (event.value == kKeyPress && event.code >= KEY_4 && event.code <= KEY_8) {
        return static_cast<char>('4' + event.code - KEY_4);
    }
    if (event.value != kKeyPress && event.value != kKeyRepeat) {
        return 0;
    }
    for (const auto& arrow : kArrows) {
        if (arrow.code == event.code) {
            return arrow.command;
        }
    }
    return 0;
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

std::vector<std::string> split(const std::string& text, char separator) {
    std::vector<std::string> parts;
    size_t start = 0;
    while (true) {
        const size_t end = text.find(separator, start);
        parts.push_back(text.substr(start, end - start));
        if (end == std::string::npos) {
            return parts;
        }
        start = end + 1;
    }
}

// Only touch LVGL when text changes, so unchanged labels are not redrawn.
void set_text(lv_obj_t* label, const std::string& text) {
    if (text == lv_label_get_text(label)) {
        return;
    }
    lv_label_set_text(label, text.c_str());
}

void show(lv_obj_t* object, bool visible) {
    lv_obj_set_flag(object, LV_OBJ_FLAG_HIDDEN, !visible);
}

lv_obj_t* label(lv_obj_t* parent, lv_style_t* style, int x, int y, int width, lv_text_align_t align) {
    auto* object = lv_label_create(parent);
    lv_obj_add_style(object, style, 0);
    lv_label_set_long_mode(object, LV_LABEL_LONG_MODE_CLIP);
    lv_obj_set_style_text_align(object, align, 0);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_width(object, width);
    lv_label_set_text(object, "");
    return object;
}

void rule(lv_obj_t* parent, lv_style_t* style, int y) {
    auto* line = lv_obj_create(parent);
    lv_obj_remove_style_all(line);
    lv_obj_add_style(line, style, 0);
    lv_obj_set_pos(line, 0, y);
    lv_obj_set_size(line, kScreenWidth, 1);
}

void apply_color(Ui& ui, uint32_t color) {
    if (color == ui.color) {
        return;
    }
    ui.color = color;
    const lv_color_t text = lv_color_hex(color);
    const lv_color_t dim = lv_color_mix(text, lv_color_hex(kBackground), kDimMix);
    lv_style_set_text_color(&ui.text, text);
    lv_style_set_text_color(&ui.dim, dim);
    lv_style_set_bg_color(&ui.rule, dim);
    lv_style_set_border_color(&ui.toast, text);
    lv_style_set_bg_color(&ui.fill, text);
    lv_obj_report_style_change(nullptr);
}

// Fills `ui` in place: LVGL objects keep pointers to its styles.
void build_ui(Ui& ui) {
    auto* screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(kBackground), 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    ui.phase = Phase::Boot;
    ui.color = 0;
    lv_style_init(&ui.text);
    lv_style_init(&ui.dim);
    lv_style_init(&ui.rule);
    lv_style_set_text_font(&ui.text, &aura_pixel_7);
    lv_style_set_text_font(&ui.dim, &aura_pixel_7);
    lv_style_set_bg_opa(&ui.rule, LV_OPA_COVER);
    lv_style_init(&ui.toast);
    lv_style_set_bg_color(&ui.toast, lv_color_hex(kBackground));
    lv_style_set_bg_opa(&ui.toast, LV_OPA_COVER);
    lv_style_set_border_width(&ui.toast, 1);
    lv_style_set_radius(&ui.toast, 0);
    lv_style_set_pad_all(&ui.toast, 0);
    lv_style_init(&ui.fill);
    lv_style_set_bg_opa(&ui.fill, LV_OPA_COVER);
    apply_color(ui, kDefaultColor);

    // Terminal header shared by both phases.
    const int full = kScreenWidth - 2 * kMargin;
    ui.title = label(screen, &ui.text, kMargin, 1, full / 2, LV_TEXT_ALIGN_LEFT);
    ui.status = label(screen, &ui.dim, kScreenWidth / 2, 1, kScreenWidth / 2 - kMargin, LV_TEXT_ALIGN_RIGHT);
    lv_label_set_text(ui.title, "AURACAM");
    rule(screen, &ui.rule, kHeaderRuleY);
    rule(screen, &ui.rule, kFooterRuleY);

    // Boot: log under the header, footer line at the bottom.
    ui.log = label(screen, &ui.text, kMargin, kLogY, full, LV_TEXT_ALIGN_LEFT);
    ui.footer = label(screen, &ui.dim, kMargin, kFooterY, full, LV_TEXT_ALIGN_LEFT);
    ui.steps = {{"BRIDGE", kStateRunning}};

    // Live: centered preview, telemetry columns, key labels.
    ui.image = lv_image_create(screen);
    lv_obj_set_pos(ui.image, kPreviewX, kPreviewY);
    ui.left = label(screen, &ui.text, kMargin, kSideY, kSideWidth, LV_TEXT_ALIGN_LEFT);
    ui.right = label(screen, &ui.text, kPreviewX + kWidth + kMargin, kSideY, kSideWidth, LV_TEXT_ALIGN_RIGHT);
    for (int i = 0; i < kActionCount; ++i) {
        ui.actions[i] = label(screen, &ui.text, i * kActionWidth, kFooterY, kActionWidth, LV_TEXT_ALIGN_CENTER);
    }

    // Quit toast: created last so it sits above everything; the bar fills
    // while Esc is held.
    ui.toast_box = lv_obj_create(screen);
    lv_obj_remove_style_all(ui.toast_box);
    lv_obj_add_style(ui.toast_box, &ui.toast, 0);
    lv_obj_set_size(ui.toast_box, kToastWidth, kToastHeight);
    lv_obj_center(ui.toast_box);
    lv_obj_remove_flag(ui.toast_box, LV_OBJ_FLAG_SCROLLABLE);
    auto* message = label(ui.toast_box, &ui.text, 0, kToastPad, kToastWidth - 2, LV_TEXT_ALIGN_CENTER);
    lv_label_set_text(message, "HOLD ESC TO QUIT");
    ui.toast_bar = lv_obj_create(ui.toast_box);
    lv_obj_remove_style_all(ui.toast_bar);
    lv_obj_add_style(ui.toast_bar, &ui.fill, 0);
    lv_obj_set_pos(ui.toast_bar, kToastPad, kToastHeight - kToastPad - kToastBarHeight - 1);
    lv_obj_set_size(ui.toast_bar, 0, kToastBarHeight);
    show(ui.toast_box, false);
}

// held_ms == 0 hides the toast; otherwise the bar shows progress to quit.
void show_toast(Ui& ui, uint32_t held_ms) {
    show(ui.toast_box, held_ms > 0);
    if (held_ms == 0) {
        return;
    }
    const int track = kToastWidth - 2 * kToastPad - 2;
    const int width = static_cast<int>(track * std::min<uint32_t>(held_ms, kQuitHoldMs) / kQuitHoldMs);
    lv_obj_set_width(ui.toast_bar, width);
}

void show_phase(Ui& ui, Phase phase) {
    ui.phase = phase;
    const bool live = phase == Phase::Live;
    show(ui.log, !live);
    show(ui.footer, !live);
    show(ui.image, live);
    show(ui.left, live);
    show(ui.right, live);
    for (auto* action : ui.actions) {
        show(action, live);
    }
}

// "> CAPTURE ENGINE .............. OK", spinner on running steps, prompt last.
std::string boot_log(const Ui& ui) {
    const char spin = kSpinner[ui.tick % sizeof(kSpinner)];
    std::string text;
    for (const auto& step : ui.steps) {
        std::string line = "> " + step.label + " ";
        if (line.size() < kLeaderColumn) {
            line.append(kLeaderColumn - line.size(), '.');
        }
        line += " ";
        line += step.state == kStateRunning ? std::string(1, spin) : step.state;
        text += line + "\n";
    }
    text += ui.cursor ? ">_" : ">";
    return text;
}

void render_boot(Ui& ui) {
    set_text(ui.log, boot_log(ui));
}

void apply_boot(Ui& ui, const std::vector<std::string>& fields) {
    ui.steps.clear();
    for (const auto& line : split(fields[kBody], '\n')) {
        const auto parts = split(line, kStateSeparator);
        if (parts.size() == 2) {
            ui.steps.push_back({parts[0], parts[1]});
        }
    }
    set_text(ui.status, fields[kHeader]);
    set_text(ui.footer, fields[kFooter]);
    render_boot(ui);
}

void apply_live(Ui& ui, const std::vector<std::string>& fields, lv_image_dsc_t& descriptor) {
    set_text(ui.status, fields[kHeader]);
    set_text(ui.left, fields[kBody]);
    set_text(ui.right, fields[kRight]);
    const auto actions = split(fields[kActions], '|');
    for (int i = 0; i < kActionCount; ++i) {
        set_text(ui.actions[i], i < static_cast<int>(actions.size()) ? actions[i] : "");
    }
    lv_image_set_src(ui.image, &descriptor);
    lv_obj_invalidate(ui.image);
}

void apply_packet(Ui& ui, const std::string& text, lv_image_dsc_t& descriptor) {
    const auto fields = split(text, kFieldSeparator);
    if (fields.size() < kFieldCount) {
        return;
    }
    apply_color(ui, std::strtoul(fields[kColor].c_str(), nullptr, 16));
    const Phase phase = fields[kKind] == "LIVE" ? Phase::Live : Phase::Boot;
    if (phase != ui.phase) {
        show_phase(ui, phase);
    }
    if (phase == Phase::Boot) {
        apply_boot(ui, fields);
        return;
    }
    apply_live(ui, fields, descriptor);
}

// Spinner and cursor run on LVGL timers so they move even between packets.
void spin(lv_timer_t* timer) {
    auto* ui = static_cast<Ui*>(lv_timer_get_user_data(timer));
    ui->tick++;
    if (ui->phase == Phase::Boot) {
        render_boot(*ui);
    }
}

void blink(lv_timer_t* timer) {
    auto* ui = static_cast<Ui*>(lv_timer_get_user_data(timer));
    ui->cursor = !ui->cursor;
    if (ui->phase == Phase::Boot) {
        render_boot(*ui);
    }
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

    // Bridge process: commands on its stdin, packets from its stdout.
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
    Ui ui{};
    build_ui(ui);
    show_phase(ui, Phase::Boot);
    render_boot(ui);
    lv_timer_create(spin, kSpinnerMs, &ui);
    lv_timer_create(blink, kCursorMs, &ui);

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
        // Keys: hold Esc to quit, 4-8 go to the bridge.
        input_event event{};
        while (read(keys, &event, sizeof(event)) == sizeof(event)) {
            if (event.type != EV_KEY) {
                continue;
            }
            if (event.code == KEY_ESC) {
                if (event.value == kKeyPress) {
                    escape_at = ticks();
                } else if (event.value == 0) {
                    escape_at = 0;
                    show_toast(ui, 0);
                }
            }
            const char command = command_for(event);
            if (command && write(commands[1], &command, 1) != 1) {
                running = 0;
            }
        }
        if (escape_at) {
            const uint32_t held = std::max<uint32_t>(1, ticks() - escape_at);
            show_toast(ui, held);
            if (held >= kQuitHoldMs) {
                running = 0;
            }
        }

        // Packets: accumulate until a whole one has arrived.
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
        usleep(kLoopSleepUs);
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
