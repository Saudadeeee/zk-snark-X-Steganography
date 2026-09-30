#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <x264.h>

static int write_nals(FILE *output, x264_nal_t *nals, int nal_count)
{
    int index;

    for (index = 0; index < nal_count; ++index)
    {
        if (nals[index].i_type == NAL_SEI)
        {
            fprintf(stderr, "SEI NAL is forbidden in the direct-CAVLC profile\n");
            return -1;
        }
        if (fwrite(nals[index].p_payload, 1u, (size_t)nals[index].i_payload, output) !=
            (size_t)nals[index].i_payload)
            return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    enum { WIDTH = 256, HEIGHT = 256, Y_SIZE = WIDTH * HEIGHT,
           C_SIZE = (WIDTH / 2) * (HEIGHT / 2) };
    uint8_t payload[] = {
        0x5A, 0x4B, 0x56, 0x50, 0x01, 0x01, 0x00, 0x00,
        0x00, 0x01, 0x11, 0x2E, 0xBD, 0x16, 0xA5
    };
    uint8_t *pixels = NULL;
    uint32_t state = UINT32_C(0x13579BDF);
    x264_param_t param;
    x264_picture_t input;
    x264_picture_t output_picture;
    x264_t *encoder = NULL;
    x264_nal_t *nals = NULL;
    int nal_count = 0;
    int encoded;
    int index;
    FILE *output = NULL;
    int result = EXIT_FAILURE;

    if (argc != 2)
    {
        fprintf(stderr, "usage: %s output.h264\n", argv[0]);
        return EXIT_FAILURE;
    }

    pixels = (uint8_t *)malloc((size_t)(Y_SIZE + 2 * C_SIZE));
    output = fopen(argv[1], "wb");
    if (!pixels || !output)
    {
        fprintf(stderr, "failed to allocate frame or create output\n");
        goto cleanup;
    }

    for (index = 0; index < Y_SIZE + 2 * C_SIZE; ++index)
    {
        state = state * UINT32_C(1664525) + UINT32_C(1013904223);
        pixels[index] = (uint8_t)(state >> 24);
    }

    if (x264_param_default_preset(&param, "ultrafast", "zerolatency") < 0)
        goto cleanup;
    param.i_csp = X264_CSP_I420;
    param.i_width = WIDTH;
    param.i_height = HEIGHT;
    param.i_fps_num = 30;
    param.i_fps_den = 1;
    param.i_threads = 1;
    param.i_bframe = 0;
    param.b_cabac = 0;
    param.analyse.intra = X264_ANALYSE_I4x4;
    param.analyse.b_transform_8x8 = 0;
    param.rc.i_rc_method = X264_RC_CRF;
    param.rc.f_rf_constant = 18.0f;
    param.zkstego_payload = payload;
    param.zkstego_payload_size = (int)sizeof(payload);
    if (x264_param_apply_profile(&param, "baseline") < 0)
        goto cleanup;

    param.b_cabac = 1;
    if (x264_encoder_open(&param))
    {
        fprintf(stderr, "encoder accepted a stego payload with CABAC enabled\n");
        goto cleanup;
    }
    param.b_cabac = 0;

    param.analyse.b_transform_8x8 = 1;
    if (x264_encoder_open(&param))
    {
        fprintf(stderr, "encoder accepted a stego payload with 8x8 transform enabled\n");
        goto cleanup;
    }
    param.analyse.b_transform_8x8 = 0;

    param.rc.i_rc_method = X264_RC_CQP;
    param.rc.i_qp_constant = 0;
    {
        x264_t *lossless_encoder = x264_encoder_open(&param);
        if (lossless_encoder)
        {
            x264_encoder_close(lossless_encoder);
            fprintf(stderr, "encoder accepted a stego payload in lossless mode\n");
            goto cleanup;
        }
    }
    param.rc.i_rc_method = X264_RC_CRF;
    param.rc.i_qp_constant = -1;
    param.rc.f_rf_constant = 18.0f;

    param.zkstego_payload_size = INT_MAX / 8 + 1;
    if (x264_encoder_open(&param))
    {
        fprintf(stderr, "encoder accepted a payload size that overflows bit indexing\n");
        goto cleanup;
    }
    param.zkstego_payload_size = (int)sizeof(payload);

    encoder = x264_encoder_open(&param);
    if (!encoder)
    {
        fprintf(stderr, "forked x264 encoder failed to open\n");
        goto cleanup;
    }
    encoded = x264_encoder_headers(encoder, &nals, &nal_count);
    if (encoded < 0 || nal_count == 0)
    {
        fprintf(stderr, "direct-payload header generation failed\n");
        goto cleanup;
    }
    for (index = 0; index < nal_count; ++index)
    {
        if (nals[index].i_type == NAL_SEI)
        {
            fprintf(stderr, "direct-payload header API emitted an SEI NAL\n");
            goto cleanup;
        }
    }

    x264_picture_init(&input);
    input.img.i_csp = X264_CSP_I420;
    input.img.i_plane = 3;
    input.img.plane[0] = pixels;
    input.img.plane[1] = pixels + Y_SIZE;
    input.img.plane[2] = pixels + Y_SIZE + C_SIZE;
    input.img.i_stride[0] = WIDTH;
    input.img.i_stride[1] = WIDTH / 2;
    input.img.i_stride[2] = WIDTH / 2;
    input.i_pts = 0;

    fprintf(stderr, "encoding one %dx%d I420 frame\n", WIDTH, HEIGHT);
    encoded = x264_encoder_encode(encoder, &nals, &nal_count, &input, &output_picture);
    if (encoded < 0 || write_nals(output, nals, nal_count) != 0)
    {
        fprintf(stderr, "first frame encode/write failed\n");
        goto cleanup;
    }

    while (x264_encoder_delayed_frames(encoder) > 0)
    {
        encoded = x264_encoder_encode(encoder, &nals, &nal_count, NULL, &output_picture);
        if (encoded < 0 || write_nals(output, nals, nal_count) != 0)
        {
            fprintf(stderr, "encoder drain failed\n");
            goto cleanup;
        }
    }

    if (fflush(output) != 0)
        goto cleanup;

    if (x264_encoder_zkstego_embedded_bits(encoder) != sizeof(payload) * 8u)
    {
        fprintf(stderr, "expected %zu embedded bits, got %llu\n", sizeof(payload) * 8u,
                (unsigned long long)x264_encoder_zkstego_embedded_bits(encoder));
        goto cleanup;
    }

    if (ftell(output) <= 0)
    {
        fprintf(stderr, "encoder emitted an empty stream\n");
        goto cleanup;
    }

    printf("PASS payload_bits=%zu output_bytes=%ld\n", sizeof(payload) * 8u, ftell(output));

    x264_encoder_close(encoder);
    encoder = NULL;
    param.analyse.intra = 0;
    encoder = x264_encoder_open(&param);
    if (!encoder)
    {
        fprintf(stderr, "encoder failed to open for non-I4x4 carrier check\n");
        goto cleanup;
    }
    input.i_pts = 1;
    encoded = x264_encoder_encode(encoder, &nals, &nal_count, &input, &output_picture);
    if (encoded < 0)
    {
        fprintf(stderr, "non-I4x4 carrier-check encode failed\n");
        goto cleanup;
    }
    while (x264_encoder_delayed_frames(encoder) > 0)
    {
        encoded = x264_encoder_encode(encoder, &nals, &nal_count, NULL, &output_picture);
        if (encoded < 0)
        {
            fprintf(stderr, "non-I4x4 carrier-check drain failed\n");
            goto cleanup;
        }
    }
    if (x264_encoder_zkstego_embedded_bits(encoder) != 0u)
    {
        fprintf(stderr, "I16x16 macroblocks consumed I4x4 blind-carrier payload bits\n");
        goto cleanup;
    }
    printf("PASS forced_i16x16_embedded_bits=0\n");
    result = EXIT_SUCCESS;

cleanup:
    if (encoder)
        x264_encoder_close(encoder);
    if (output)
        fclose(output);
    free(pixels);
    return result;
}
