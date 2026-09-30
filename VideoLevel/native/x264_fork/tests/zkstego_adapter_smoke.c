#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "zkstego_x264.h"

typedef struct {
    size_t nal_count;
    size_t output_bytes;
} OutputStats;

static int count_nal(const uint8_t *annexb, size_t size, void *opaque)
{
    OutputStats *stats = (OutputStats *)opaque;
    if (!annexb || size == 0u || !stats)
        return ZKS_ERR_ARGUMENT;
    ++stats->nal_count;
    stats->output_bytes += size;
    return ZKS_OK;
}

int main(void)
{
    enum { WIDTH = 64, HEIGHT = 64, Y_SIZE = WIDTH * HEIGHT,
           C_SIZE = (WIDTH / 2) * (HEIGHT / 2) };
    uint8_t payload[] = { 0xA5 };
    uint8_t *pixels = (uint8_t *)malloc((size_t)(Y_SIZE + 2 * C_SIZE));
    uint32_t state = UINT32_C(0x13579BDF);
    ZksX264Config config = { 0 };
    ZksX264Encoder *encoder = NULL;
    OutputStats stats = { 0u, 0u };
    int index;
    int status;

    if (!pixels)
        return EXIT_FAILURE;
    for (index = 0; index < Y_SIZE + 2 * C_SIZE; ++index)
    {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        pixels[index] = (uint8_t)(state >> 24);
    }

    config.width = WIDTH;
    config.height = HEIGHT;
    config.fps_num = 30;
    config.fps_den = 1;
    config.keyint = 30;
    config.crf = 18;
    config.direct_payload = payload;
    config.direct_payload_size = (size_t)(INT_MAX / 8) + 1u;
    encoder = (ZksX264Encoder *)(void *)&config;
    status = zks_x264_encoder_open(&config, &encoder);
    if (status != ZKS_ERR_ARGUMENT || encoder != NULL)
    {
        fprintf(stderr, "adapter did not reject overflowing payload size\n");
        free(pixels);
        return EXIT_FAILURE;
    }

    config.direct_payload_size = sizeof(payload);
    status = zks_x264_encoder_open(&config, &encoder);
    if (status != ZKS_OK || !encoder)
    {
        fprintf(stderr, "adapter encoder open failed: %d\n", status);
        free(pixels);
        return EXIT_FAILURE;
    }

    status = zks_x264_encoder_encode_i420(
        encoder,
        pixels, WIDTH,
        pixels + Y_SIZE, WIDTH / 2,
        pixels + Y_SIZE + C_SIZE, WIDTH / 2,
        0,
        count_nal,
        &stats
    );
    if (status != ZKS_OK ||
        zks_x264_encoder_finish(encoder, count_nal, &stats) != ZKS_OK ||
        stats.nal_count == 0u || stats.output_bytes == 0u ||
        zks_x264_encoder_embedded_bits(encoder) != 8u)
    {
        fprintf(stderr, "adapter encode failed: status=%d nals=%zu bits=%llu\n",
                status, stats.nal_count,
                (unsigned long long)zks_x264_encoder_embedded_bits(encoder));
        zks_x264_encoder_close(encoder);
        free(pixels);
        return EXIT_FAILURE;
    }

    printf("PASS adapter_nals=%zu output_bytes=%zu embedded_bits=8\n",
           stats.nal_count, stats.output_bytes);
    zks_x264_encoder_close(encoder);
    encoder = NULL;

    config.direct_payload_size = 3u;
    if (zks_x264_encoder_open(&config, &encoder) != ZKS_OK || !encoder)
    {
        fprintf(stderr, "capacity-test encoder open failed\n");
        free(pixels);
        return EXIT_FAILURE;
    }
    status = zks_x264_encoder_encode_i420(
        encoder,
        pixels, WIDTH,
        pixels + Y_SIZE, WIDTH / 2,
        pixels + Y_SIZE + C_SIZE, WIDTH / 2,
        0,
        count_nal,
        &stats
    );
    if (status != ZKS_OK ||
        zks_x264_encoder_finish(encoder, count_nal, &stats) != ZKS_ERR_CAPACITY ||
        zks_x264_encoder_embedded_bits(encoder) >= 24u)
    {
        fprintf(stderr, "adapter did not reject a payload exceeding frame capacity\n");
        zks_x264_encoder_close(encoder);
        free(pixels);
        return EXIT_FAILURE;
    }
    printf("PASS adapter_capacity_rejected embedded_bits=%llu requested_bits=24\n",
           (unsigned long long)zks_x264_encoder_embedded_bits(encoder));
    zks_x264_encoder_close(encoder);
    free(pixels);
    return EXIT_SUCCESS;
}
