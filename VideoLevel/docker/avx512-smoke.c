/*
 * Instruction-compatibility smoke test for QEMU TCG only.
 *
 * Passing this file proves that the emulator can execute one AVX-512F
 * instruction sequence. It is deliberately not a performance test and does
 * not establish compatibility with every AVX-512 extension used by LaZer.
 */
#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>

int main(void) {
    volatile int32_t left_value = 7;
    volatile int32_t right_value = 11;
    const __m512i left = _mm512_set1_epi32(left_value);
    const __m512i right = _mm512_set1_epi32(right_value);
    const __m512i sum = _mm512_add_epi32(left, right);
    int32_t lanes[16];

    _mm512_storeu_si512((void *)lanes, sum);
    for (size_t lane = 0; lane < 16; ++lane) {
        if (lanes[lane] != 18) {
            fprintf(stderr, "lane %zu was %d, expected 18\n", lane, lanes[lane]);
            return 1;
        }
    }

    puts("AVX-512F QEMU compatibility smoke test passed (16 x 32-bit lanes)");
    return 0;
}
