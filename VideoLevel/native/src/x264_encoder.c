#include "zkstego_x264.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

#include <x264.h>

struct ZksX264Encoder {
    x264_t *encoder;
    uint8_t *direct_payload;
    size_t direct_payload_size;
    int finished;
    int finish_status;
};

int zks_x264_encoder_open(const ZksX264Config *config, ZksX264Encoder **out_encoder) {
    x264_param_t param;
    ZksX264Encoder *state;
    int keyint;
    if (!out_encoder) {
        return ZKS_ERR_ARGUMENT;
    }
    *out_encoder = NULL;
    if (!config || config->width <= 0 || config->height <= 0 ||
        (config->width & 1) || (config->height & 1) || config->fps_num <= 0 || config->fps_den <= 0) {
        return ZKS_ERR_ARGUMENT;
    }
    if (config->direct_payload_size > (size_t)(INT_MAX / 8) ||
        (config->direct_payload_size != 0u && !config->direct_payload)) {
        return ZKS_ERR_ARGUMENT;
    }
    if (x264_param_default_preset(&param, "ultrafast", "zerolatency") < 0) {
        return ZKS_ERR_FORMAT;
    }
    keyint = config->keyint > 0 ? config->keyint : 30;
    param.i_csp = X264_CSP_I420;
    param.i_width = config->width;
    param.i_height = config->height;
    param.i_fps_num = config->fps_num;
    param.i_fps_den = config->fps_den;
    param.b_vfr_input = 0;
    param.b_annexb = 1;
    param.b_repeat_headers = 1;
    param.b_aud = 1;
    param.b_cabac = 0;
    param.i_threads = 1;
    param.b_sliced_threads = 0;
    param.analyse.b_transform_8x8 = 0;
    param.analyse.intra = X264_ANALYSE_I4x4;
    if (config->direct_payload_size != 0u) {
        param.analyse.i_trellis = 1;
    }
    param.i_keyint_max = keyint;
    param.i_keyint_min = keyint;
    param.i_bframe = 0;
    param.rc.i_rc_method = X264_RC_CRF;
    param.rc.f_rf_constant = (float)(config->crf > 0 ? config->crf : 23);
    if (x264_param_apply_profile(&param, "baseline") < 0) {
        return ZKS_ERR_FORMAT;
    }
    state = (ZksX264Encoder *)calloc(1u, sizeof(*state));
    if (!state) {
        return ZKS_ERR_MEMORY;
    }
    if (config->direct_payload_size != 0u) {
        state->direct_payload = (uint8_t *)malloc(config->direct_payload_size);
        if (!state->direct_payload) {
            free(state);
            return ZKS_ERR_MEMORY;
        }
        memcpy(state->direct_payload, config->direct_payload, config->direct_payload_size);
        param.zkstego_payload = state->direct_payload;
        param.zkstego_payload_size = (int)config->direct_payload_size;
    }
    state->direct_payload_size = config->direct_payload_size;
    state->encoder = x264_encoder_open(&param);
    if (!state->encoder) {
        free(state->direct_payload);
        free(state);
        return ZKS_ERR_FORMAT;
    }
    *out_encoder = state;
    return ZKS_OK;
}

int zks_x264_encoder_encode_i420(
    ZksX264Encoder *encoder,
    const uint8_t *y, int y_stride,
    const uint8_t *u, int u_stride,
    const uint8_t *v, int v_stride,
    int64_t pts,
    ZksEncodedNalCallback callback,
    void *opaque
) {
    x264_picture_t input;
    x264_picture_t output;
    x264_nal_t *nals = NULL;
    int nal_count = 0;
    int encoded;
    int index;
    int callback_status;
    if (!encoder || !encoder->encoder || encoder->finished || !y || !u || !v ||
        y_stride <= 0 || u_stride <= 0 || v_stride <= 0) {
        return ZKS_ERR_ARGUMENT;
    }
    x264_picture_init(&input);
    if (encoder->direct_payload_size != 0u &&
        x264_encoder_zkstego_embedded_bits(encoder->encoder) <
            (uint64_t)encoder->direct_payload_size * 8u) {
        input.i_type = X264_TYPE_IDR;
    }
    input.img.i_csp = X264_CSP_I420;
    input.img.i_plane = 3;
    input.img.plane[0] = (uint8_t *)y;
    input.img.plane[1] = (uint8_t *)u;
    input.img.plane[2] = (uint8_t *)v;
    input.img.i_stride[0] = y_stride;
    input.img.i_stride[1] = u_stride;
    input.img.i_stride[2] = v_stride;
    input.i_pts = pts;
    encoded = x264_encoder_encode(encoder->encoder, &nals, &nal_count, &input, &output);
    if (encoded < 0) {
        return ZKS_ERR_FORMAT;
    }
    if (callback) {
        for (index = 0; index < nal_count; ++index) {
            callback_status = callback(nals[index].p_payload, (size_t)nals[index].i_payload, opaque);
            if (callback_status != ZKS_OK) {
                return ZKS_ERR_CALLBACK;
            }
        }
    }
    return ZKS_OK;
}

int zks_x264_encoder_finish(
    ZksX264Encoder *encoder,
    ZksEncodedNalCallback callback,
    void *opaque
) {
    x264_picture_t output;
    x264_nal_t *nals = NULL;
    int nal_count = 0;
    int encoded;
    int index;
    int callback_status;
    if (!encoder || !encoder->encoder) {
        return ZKS_ERR_ARGUMENT;
    }
    if (encoder->finished) {
        return encoder->finish_status;
    }
    while (x264_encoder_delayed_frames(encoder->encoder) > 0) {
        encoded = x264_encoder_encode(encoder->encoder, &nals, &nal_count, NULL, &output);
        if (encoded < 0) {
            encoder->finish_status = ZKS_ERR_FORMAT;
            encoder->finished = 1;
            return encoder->finish_status;
        }
        if (callback) {
            for (index = 0; index < nal_count; ++index) {
                callback_status = callback(
                    nals[index].p_payload,
                    (size_t)nals[index].i_payload,
                    opaque
                );
                if (callback_status != ZKS_OK) {
                    encoder->finish_status = ZKS_ERR_CALLBACK;
                    encoder->finished = 1;
                    return encoder->finish_status;
                }
            }
        }
    }
    encoder->finished = 1;
    encoder->finish_status =
        x264_encoder_zkstego_embedded_bits(encoder->encoder) ==
                (uint64_t)encoder->direct_payload_size * UINT64_C(8)
            ? ZKS_OK
            : ZKS_ERR_CAPACITY;
    return encoder->finish_status;
}

uint64_t zks_x264_encoder_embedded_bits(const ZksX264Encoder *encoder) {
    if (!encoder || !encoder->encoder) {
        return 0u;
    }
    return x264_encoder_zkstego_embedded_bits(encoder->encoder);
}

void zks_x264_encoder_close(ZksX264Encoder *encoder) {
    if (!encoder) {
        return;
    }
    if (encoder->encoder) {
        x264_encoder_close(encoder->encoder);
    }
    free(encoder->direct_payload);
    free(encoder);
}
