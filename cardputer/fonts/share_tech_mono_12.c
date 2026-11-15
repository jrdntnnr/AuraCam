/*******************************************************************************
 * Size: 12 px
 * Bpp: 2
 * Opts: --font ShareTechMono-Regular.ttf --size 12 --bpp 2 --format lvgl --range 0x20-0x7E --no-compress -o cardputer/fonts/share_tech_mono_12.c
 ******************************************************************************/

#ifdef LV_LVGL_H_INCLUDE_SIMPLE
#include "lvgl.h"
#else
#include "lvgl/lvgl.h"
#endif

#ifndef SHARE_TECH_MONO_12
#define SHARE_TECH_MONO_12 1
#endif

#if SHARE_TECH_MONO_12

/*-----------------
 *    BITMAPS
 *----------------*/

/*Store the image of the glyphs*/
static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {
    /* U+0020 " " */

    /* U+0021 "!" */
    0x77, 0x77, 0x76, 0x7,

    /* U+0022 "\"" */
    0x76, 0x36, 0x22,

    /* U+0023 "#" */
    0xd, 0x80, 0xd8, 0x3f, 0xd0, 0xd8, 0xd, 0x83,
    0xfd, 0xd, 0x80, 0xd8,

    /* U+0024 "$" */
    0x4, 0x7, 0x3, 0xf2, 0x40, 0x90, 0xf, 0x80,
    0x30, 0xc, 0x3, 0x1f, 0x81, 0xc0, 0x10,

    /* U+0025 "%" */
    0x7c, 0x2, 0x54, 0x2, 0x80, 0x1a, 0xa8, 0x1,
    0xd0, 0xc, 0xc0, 0x33, 0x0, 0xb8,

    /* U+0026 "&" */
    0x7d, 0x34, 0xd, 0x1, 0xff, 0xc3, 0x30, 0xcc,
    0x31, 0xfc,

    /* U+0027 "'" */
    0x76, 0x20,

    /* U+0028 "(" */
    0x11, 0x89, 0x30, 0xc3, 0xc, 0x30, 0xc3, 0x9,
    0xc,

    /* U+0029 ")" */
    0x41, 0xc3, 0x9, 0x24, 0x92, 0x49, 0x24, 0x93,
    0x24,

    /* U+002A "*" */
    0x6, 0x2, 0x69, 0xf, 0x41, 0xd8, 0x0, 0x40,

    /* U+002B "+" */
    0x2, 0x0, 0x20, 0x3f, 0xd0, 0x20, 0x1, 0x0,

    /* U+002C "," */
    0x30, 0xc6, 0x0,

    /* U+002D "-" */
    0xbf, 0x0,

    /* U+002E "." */
    0x7,

    /* U+002F "/" */
    0x0, 0x60, 0x9, 0x0, 0xc0, 0x18, 0x3, 0x0,
    0x60, 0x9, 0x0, 0xc0, 0x18, 0x3, 0x0, 0x30,
    0x0,

    /* U+0030 "0" */
    0x7e, 0x34, 0xdc, 0x37, 0x3d, 0xf6, 0x78, 0x9d,
    0x35, 0xf8,

    /* U+0031 "1" */
    0x7c, 0x13, 0x0, 0xc0, 0x30, 0xc, 0x3, 0x0,
    0xc2, 0xfc,

    /* U+0032 "2" */
    0x7d, 0x0, 0xc0, 0x30, 0x1c, 0xd, 0xa, 0x7,
    0x2, 0xfc,

    /* U+0033 "3" */
    0x7d, 0x0, 0xc0, 0x70, 0xf4, 0x3, 0x0, 0xc0,
    0x31, 0xf4,

    /* U+0034 "4" */
    0x30, 0xc, 0x6, 0x12, 0x58, 0xc6, 0x3f, 0xd0,
    0x60, 0x18,

    /* U+0035 "5" */
    0x7f, 0x18, 0x6, 0x1, 0xf4, 0x3, 0x0, 0xc0,
    0x32, 0xf4,

    /* U+0036 "6" */
    0x7e, 0x34, 0xc, 0x3, 0xf8, 0xc2, 0x70, 0x9d,
    0x35, 0xf8,

    /* U+0037 "7" */
    0xbf, 0x0, 0xc0, 0x60, 0x24, 0xc, 0x7, 0x2,
    0x40, 0xc0,

    /* U+0038 "8" */
    0x7e, 0x34, 0xdd, 0x31, 0xfc, 0xd3, 0x70, 0x9c,
    0x25, 0xfc,

    /* U+0039 "9" */
    0x7e, 0x34, 0xdc, 0x27, 0x49, 0x7f, 0x40, 0x90,
    0x34, 0xf8,

    /* U+003A ":" */
    0x70, 0x0, 0x7,

    /* U+003B ";" */
    0x30, 0x0, 0x0, 0x0, 0xc3, 0x14,

    /* U+003C "<" */
    0x0, 0x50, 0x7c, 0x38, 0x3, 0x90, 0x7, 0xd0,
    0x5,

    /* U+003D "=" */
    0x3f, 0xd0, 0x0, 0x3f, 0xd0,

    /* U+003E ">" */
    0x20, 0x2, 0xe0, 0x1, 0xd0, 0x1d, 0x2e, 0x1,
    0x0,

    /* U+003F "?" */
    0x7d, 0x3, 0x3, 0xd, 0x28, 0x10, 0x0, 0x28,

    /* U+0040 "@" */
    0x3f, 0xe2, 0x69, 0xc9, 0x9a, 0x26, 0x68, 0x99,
    0xa2, 0x2e, 0x88, 0xa, 0x1f, 0xc0,

    /* U+0041 "A" */
    0xb, 0x0, 0xe4, 0xd, 0x81, 0x8c, 0x24, 0xc3,
    0xfd, 0x30, 0x66, 0x3,

    /* U+0042 "B" */
    0xfe, 0x30, 0xdc, 0x37, 0xfc, 0xc2, 0x70, 0x9c,
    0x27, 0xfc,

    /* U+0043 "C" */
    0x3f, 0x28, 0x9, 0x2, 0x40, 0x90, 0x24, 0x9,
    0x0, 0xfc,

    /* U+0044 "D" */
    0x3f, 0xc3, 0x9, 0x30, 0xa3, 0xa, 0x30, 0xa3,
    0xa, 0x30, 0x93, 0xfc,

    /* U+0045 "E" */
    0xff, 0x34, 0xd, 0x3, 0xfc, 0xd0, 0x34, 0xd,
    0x3, 0xfc,

    /* U+0046 "F" */
    0xbf, 0x24, 0x9, 0x2, 0xfc, 0x90, 0x24, 0x9,
    0x2, 0x40,

    /* U+0047 "G" */
    0x7f, 0x34, 0xc, 0x3, 0x0, 0xcb, 0x70, 0x9d,
    0x25, 0xfd,

    /* U+0048 "H" */
    0x30, 0xa3, 0xa, 0x30, 0xa3, 0xfe, 0x30, 0xa3,
    0xa, 0x30, 0xa3, 0xa,

    /* U+0049 "I" */
    0x7e, 0x1c, 0x1c, 0x1c, 0x1c, 0x1c, 0x1c, 0x7e,

    /* U+004A "J" */
    0x3f, 0x3, 0x3, 0x3, 0x3, 0x3, 0x7, 0x7d,

    /* U+004B "K" */
    0x30, 0xc3, 0x24, 0x37, 0x3, 0xd0, 0x3e, 0x3,
    0x30, 0x31, 0xc3, 0xd,

    /* U+004C "L" */
    0x90, 0x24, 0x9, 0x2, 0x40, 0x90, 0x24, 0x9,
    0x2, 0xfc,

    /* U+004D "M" */
    0x74, 0xf7, 0x8f, 0x6d, 0xb6, 0xe7, 0x67, 0x36,
    0x3, 0x60, 0x36, 0x3,

    /* U+004E "N" */
    0x3c, 0x63, 0xc6, 0x39, 0x63, 0x66, 0x33, 0x63,
    0x3a, 0x32, 0xe3, 0x1e,

    /* U+004F "O" */
    0x1f, 0xc3, 0xa, 0x30, 0x63, 0x6, 0x30, 0x63,
    0x6, 0x30, 0xa2, 0xfc,

    /* U+0050 "P" */
    0xfe, 0x30, 0x9c, 0x27, 0x9, 0xfe, 0x30, 0xc,
    0x3, 0x0,

    /* U+0051 "Q" */
    0x1f, 0xc0, 0xc2, 0x83, 0x6, 0xc, 0x18, 0x30,
    0x60, 0xc1, 0x83, 0xa, 0xb, 0xf8, 0x0, 0x10,

    /* U+0052 "R" */
    0x3f, 0x83, 0xc, 0x30, 0xc3, 0xc, 0x3f, 0x83,
    0x24, 0x30, 0xc3, 0x9,

    /* U+0053 "S" */
    0x7f, 0x24, 0x9, 0x1, 0xf8, 0x3, 0x0, 0xd0,
    0x32, 0xf8,

    /* U+0054 "T" */
    0x3f, 0xe0, 0x70, 0x7, 0x0, 0x70, 0x7, 0x0,
    0x70, 0x7, 0x0, 0x70,

    /* U+0055 "U" */
    0x30, 0xa3, 0xa, 0x30, 0xa3, 0xa, 0x30, 0xa3,
    0xa, 0x30, 0x91, 0xfc,

    /* U+0056 "V" */
    0x30, 0x63, 0x9, 0x30, 0xc2, 0x4c, 0x19, 0x80,
    0xd4, 0xf, 0x0, 0xb0,

    /* U+0057 "W" */
    0x60, 0x36, 0x2, 0x60, 0x22, 0x12, 0x27, 0x23,
    0xa6, 0x39, 0xd3, 0x8d,

    /* U+0058 "X" */
    0x30, 0x91, 0x8c, 0xf, 0x40, 0x70, 0xb, 0x0,
    0xe8, 0x24, 0xc3, 0xa,

    /* U+0059 "Y" */
    0x30, 0x62, 0x4c, 0xd, 0x80, 0xb0, 0x7, 0x0,
    0x70, 0x7, 0x0, 0x70,

    /* U+005A "Z" */
    0xbf, 0x40, 0xc0, 0xa0, 0x30, 0x28, 0xc, 0x9,
    0x3, 0xfd,

    /* U+005B "[" */
    0x3d, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30, 0x30,
    0x30, 0x30, 0x3d,

    /* U+005C "\\" */
    0x30, 0x3, 0x0, 0x18, 0x0, 0xc0, 0x9, 0x0,
    0x60, 0x3, 0x0, 0x18, 0x0, 0xc0, 0x9, 0x0,
    0x60,

    /* U+005D "]" */
    0x3d, 0x6, 0x6, 0x6, 0x6, 0x6, 0x6, 0x6,
    0x6, 0x6, 0x3d,

    /* U+005E "^" */
    0xb, 0x0, 0xd8, 0x28, 0xc3, 0x9,

    /* U+005F "_" */
    0xbf, 0xf0,

    /* U+0060 "`" */
    0x10, 0xc,

    /* U+0061 "a" */
    0x2f, 0x40, 0xc, 0x2f, 0xc3, 0xc, 0x30, 0xc2,
    0xfe,

    /* U+0062 "b" */
    0xc0, 0x30, 0xf, 0xf3, 0x9, 0xc2, 0x70, 0x9c,
    0x27, 0xfc,

    /* U+0063 "c" */
    0x3f, 0x28, 0x9, 0x2, 0x40, 0xa0, 0xf, 0xc0,

    /* U+0064 "d" */
    0x2, 0x40, 0x97, 0xf7, 0x9, 0xc2, 0x70, 0x9c,
    0x25, 0xfd,

    /* U+0065 "e" */
    0x7f, 0x30, 0x9f, 0xf7, 0x0, 0xd0, 0x1f, 0xc0,

    /* U+0066 "f" */
    0x2f, 0x4c, 0xb, 0xf0, 0xc0, 0x30, 0xc, 0x3,
    0x2, 0xf8,

    /* U+0067 "g" */
    0x2f, 0xd3, 0x9, 0x30, 0x92, 0xf8, 0x18, 0x1,
    0xfc, 0x0, 0xa3, 0xfc,

    /* U+0068 "h" */
    0xc0, 0x30, 0xf, 0xf3, 0x9, 0xc2, 0x70, 0x9c,
    0x27, 0x9,

    /* U+0069 "i" */
    0x7, 0x0, 0x0, 0x3f, 0x0, 0x70, 0x7, 0x0,
    0x70, 0x7, 0x0, 0x7d,

    /* U+006A "j" */
    0x7, 0x0, 0x3f, 0x7, 0x7, 0x7, 0x7, 0x7,
    0x7, 0x7d,

    /* U+006B "k" */
    0xc0, 0x30, 0xc, 0x73, 0x70, 0xf4, 0x3b, 0xc,
    0xa3, 0xc,

    /* U+006C "l" */
    0x3e, 0x0, 0x60, 0x6, 0x0, 0x60, 0x6, 0x0,
    0x60, 0x6, 0x0, 0x3e,

    /* U+006D "m" */
    0x7e, 0xe6, 0x73, 0x52, 0x35, 0x23, 0x52, 0x35,
    0x23,

    /* U+006E "n" */
    0xff, 0x30, 0x9c, 0x27, 0x9, 0xc2, 0x70, 0x90,

    /* U+006F "o" */
    0x7f, 0x30, 0x9c, 0x27, 0x9, 0xc2, 0x5f, 0xc0,

    /* U+0070 "p" */
    0xff, 0x30, 0x9c, 0x27, 0x9, 0xc2, 0x7f, 0xcc,
    0x3, 0x0,

    /* U+0071 "q" */
    0x7f, 0x70, 0x9c, 0x27, 0x9, 0xc2, 0x5f, 0xd0,
    0x24, 0x9,

    /* U+0072 "r" */
    0xbf, 0xc, 0x3, 0x0, 0xc0, 0x30, 0x2f, 0x40,

    /* U+0073 "s" */
    0x7f, 0x28, 0x7, 0xe0, 0xc, 0x3, 0x1f, 0x80,

    /* U+0074 "t" */
    0x10, 0x9, 0xb, 0xf0, 0x90, 0x24, 0x9, 0x2,
    0x40, 0x7c,

    /* U+0075 "u" */
    0xc2, 0x70, 0x9c, 0x27, 0x9, 0xc2, 0x5f, 0xd0,

    /* U+0076 "v" */
    0x30, 0x63, 0x4d, 0x28, 0xc0, 0xd8, 0xe, 0x40,
    0xb0,

    /* U+0077 "w" */
    0x60, 0x31, 0x88, 0xc3, 0x76, 0xe, 0xe4, 0x3d,
    0xd0, 0xa7, 0x0,

    /* U+0078 "x" */
    0x34, 0xc0, 0xe8, 0xb, 0x0, 0xb0, 0x1d, 0xc3,
    0xd,

    /* U+0079 "y" */
    0x30, 0x63, 0x49, 0x18, 0xc0, 0xc8, 0xe, 0x40,
    0x70, 0x3, 0x1, 0xd0,

    /* U+007A "z" */
    0x7f, 0x1, 0xc0, 0xc0, 0xa0, 0x70, 0x2f, 0xc0,

    /* U+007B "{" */
    0xe, 0x18, 0x18, 0x18, 0x24, 0x30, 0x24, 0x18,
    0x18, 0x18, 0xe,

    /* U+007C "|" */
    0x22, 0x22, 0x22, 0x22, 0x22, 0x20,

    /* U+007D "}" */
    0x38, 0xc, 0xc, 0xc, 0xc, 0xa, 0xc, 0xc,
    0xc, 0xc, 0x38,

    /* U+007E "~" */
    0xff, 0x40
};


/*---------------------
 *  GLYPH DESCRIPTION
 *--------------------*/

static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {
    {.bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0} /* id = 0 reserved */,
    {.bitmap_index = 0, .adv_w = 104, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 0, .adv_w = 104, .box_w = 2, .box_h = 8, .ofs_x = 2, .ofs_y = 0},
    {.bitmap_index = 4, .adv_w = 104, .box_w = 4, .box_h = 3, .ofs_x = 1, .ofs_y = 5},
    {.bitmap_index = 7, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 19, .adv_w = 104, .box_w = 5, .box_h = 12, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 34, .adv_w = 104, .box_w = 7, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 48, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 58, .adv_w = 104, .box_w = 2, .box_h = 3, .ofs_x = 2, .ofs_y = 5},
    {.bitmap_index = 60, .adv_w = 104, .box_w = 3, .box_h = 12, .ofs_x = 2, .ofs_y = -1},
    {.bitmap_index = 69, .adv_w = 104, .box_w = 3, .box_h = 12, .ofs_x = 2, .ofs_y = -1},
    {.bitmap_index = 78, .adv_w = 104, .box_w = 6, .box_h = 5, .ofs_x = 0, .ofs_y = 3},
    {.bitmap_index = 86, .adv_w = 104, .box_w = 6, .box_h = 5, .ofs_x = 0, .ofs_y = 1},
    {.bitmap_index = 94, .adv_w = 104, .box_w = 3, .box_h = 3, .ofs_x = 2, .ofs_y = -2},
    {.bitmap_index = 97, .adv_w = 104, .box_w = 5, .box_h = 1, .ofs_x = 1, .ofs_y = 3},
    {.bitmap_index = 99, .adv_w = 104, .box_w = 2, .box_h = 2, .ofs_x = 2, .ofs_y = 0},
    {.bitmap_index = 100, .adv_w = 104, .box_w = 6, .box_h = 11, .ofs_x = 0, .ofs_y = -1},
    {.bitmap_index = 117, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 127, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 137, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 147, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 157, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 167, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 177, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 187, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 197, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 207, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 217, .adv_w = 104, .box_w = 2, .box_h = 6, .ofs_x = 2, .ofs_y = 0},
    {.bitmap_index = 220, .adv_w = 104, .box_w = 3, .box_h = 8, .ofs_x = 2, .ofs_y = -2},
    {.bitmap_index = 226, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 1},
    {.bitmap_index = 235, .adv_w = 104, .box_w = 6, .box_h = 3, .ofs_x = 0, .ofs_y = 2},
    {.bitmap_index = 240, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 1},
    {.bitmap_index = 249, .adv_w = 104, .box_w = 4, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 257, .adv_w = 104, .box_w = 7, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 271, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 283, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 293, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 303, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 315, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 325, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 335, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 345, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 357, .adv_w = 104, .box_w = 4, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 365, .adv_w = 104, .box_w = 4, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 373, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 385, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 395, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 407, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 419, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 431, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 441, .adv_w = 104, .box_w = 7, .box_h = 9, .ofs_x = 0, .ofs_y = -1},
    {.bitmap_index = 457, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 469, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 479, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 491, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 503, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 515, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 527, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 539, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 551, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 561, .adv_w = 104, .box_w = 4, .box_h = 11, .ofs_x = 1, .ofs_y = -1},
    {.bitmap_index = 572, .adv_w = 104, .box_w = 6, .box_h = 11, .ofs_x = 0, .ofs_y = -1},
    {.bitmap_index = 589, .adv_w = 104, .box_w = 4, .box_h = 11, .ofs_x = 1, .ofs_y = -1},
    {.bitmap_index = 600, .adv_w = 104, .box_w = 6, .box_h = 4, .ofs_x = 0, .ofs_y = 5},
    {.bitmap_index = 606, .adv_w = 104, .box_w = 7, .box_h = 1, .ofs_x = 0, .ofs_y = -2},
    {.bitmap_index = 608, .adv_w = 104, .box_w = 4, .box_h = 2, .ofs_x = 1, .ofs_y = 7},
    {.bitmap_index = 610, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 619, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 629, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 637, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 647, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 655, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 665, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = -2},
    {.bitmap_index = 677, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 687, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 699, .adv_w = 104, .box_w = 4, .box_h = 10, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 709, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 719, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 731, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 740, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 748, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 756, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 766, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 776, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 784, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 792, .adv_w = 104, .box_w = 5, .box_h = 8, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 802, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 810, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 819, .adv_w = 104, .box_w = 7, .box_h = 6, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 830, .adv_w = 104, .box_w = 6, .box_h = 6, .ofs_x = 0, .ofs_y = 0},
    {.bitmap_index = 839, .adv_w = 104, .box_w = 6, .box_h = 8, .ofs_x = 0, .ofs_y = -2},
    {.bitmap_index = 851, .adv_w = 104, .box_w = 5, .box_h = 6, .ofs_x = 1, .ofs_y = 0},
    {.bitmap_index = 859, .adv_w = 104, .box_w = 4, .box_h = 11, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 870, .adv_w = 104, .box_w = 2, .box_h = 11, .ofs_x = 2, .ofs_y = -1},
    {.bitmap_index = 876, .adv_w = 104, .box_w = 4, .box_h = 11, .ofs_x = 1, .ofs_y = -2},
    {.bitmap_index = 887, .adv_w = 104, .box_w = 5, .box_h = 1, .ofs_x = 1, .ofs_y = 3}
};

/*---------------------
 *  CHARACTER MAPPING
 *--------------------*/



/*Collect the unicode lists and glyph_id offsets*/
static const lv_font_fmt_txt_cmap_t cmaps[] =
{
    {
        .range_start = 32, .range_length = 95, .glyph_id_start = 1,
        .unicode_list = NULL, .glyph_id_ofs_list = NULL, .list_length = 0, .type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY
    }
};



/*--------------------
 *  ALL CUSTOM DATA
 *--------------------*/

#if LVGL_VERSION_MAJOR == 8
/*Store all the custom data of the font*/
static  lv_font_fmt_txt_glyph_cache_t cache;
#endif

#if LVGL_VERSION_MAJOR >= 8
static const lv_font_fmt_txt_dsc_t font_dsc = {
#else
static lv_font_fmt_txt_dsc_t font_dsc = {
#endif
    .glyph_bitmap = glyph_bitmap,
    .glyph_dsc = glyph_dsc,
    .cmaps = cmaps,
    .kern_dsc = NULL,
    .kern_scale = 0,
    .cmap_num = 1,
    .bpp = 2,
    .kern_classes = 0,
    .bitmap_format = 0,
#if LVGL_VERSION_MAJOR == 8
    .cache = &cache
#endif
};



/*-----------------
 *  PUBLIC FONT
 *----------------*/

/*Initialize a public general font descriptor*/
#if LVGL_VERSION_MAJOR >= 8
const lv_font_t share_tech_mono_12 = {
#else
lv_font_t share_tech_mono_12 = {
#endif
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,    /*Function pointer to get glyph's data*/
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,    /*Function pointer to get glyph's bitmap*/
    .line_height = 13,          /*The maximum line height required by the font*/
    .base_line = 2,             /*Baseline measured from the bottom of the line*/
#if !(LVGL_VERSION_MAJOR == 6 && LVGL_VERSION_MINOR == 0)
    .subpx = LV_FONT_SUBPX_NONE,
#endif
#if LV_VERSION_CHECK(7, 4, 0) || LVGL_VERSION_MAJOR >= 8
    .underline_position = -1,
    .underline_thickness = 1,
#endif
    .dsc = &font_dsc,          /*The custom font data. Will be accessed by `get_glyph_bitmap/dsc` */
#if LV_VERSION_CHECK(8, 2, 0) || LVGL_VERSION_MAJOR >= 9
    .fallback = NULL,
#endif
    .user_data = NULL,
};



#endif /*#if SHARE_TECH_MONO_12*/

