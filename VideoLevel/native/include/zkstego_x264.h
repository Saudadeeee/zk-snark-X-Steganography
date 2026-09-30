#ifndef ZKSTEGO_X264_H
#define ZKSTEGO_X264_H

#include <stddef.h>
#include <stdint.h>

#include "zkstego_live.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ZksX264Encoder ZksX264Encoder;

typedef struct {
    int width;
    int height;
    int fps_num;
    int fps_den;
    int keyint;
    int crf;
    /* Only accepted by the patched x264 fork in native/x264_fork/. */
    const uint8_t *direct_payload;
    size_t direct_payload_size;
} ZksX264Config;

typedef int (*ZksEncodedNalCallback)(const uint8_t *annexb, size_t size, void *opaque);

/*
 * Open a low-latency H.264 encoder with the enforced live profile:
 * Baseline, CAVLC, AUD enabled, Annex-B output, fixed keyframe interval and
 * no B frames. The caller owns the Y/U/V buffers supplied to encode_i420.
 */
int zks_x264_encoder_open(const ZksX264Config *config, ZksX264Encoder **out_encoder);
int zks_x264_encoder_encode_i420(
    ZksX264Encoder *encoder,
    const uint8_t *y, int y_stride,
    const uint8_t *u, int u_stride,
    const uint8_t *v, int v_stride,
    int64_t pts,
    ZksEncodedNalCallback callback,
    void *opaque
);
/* Drain delayed frames and reject if the full requested payload did not fit.
 * Do not publish callback output until this returns ZKS_OK. */
int zks_x264_encoder_finish(
    ZksX264Encoder *encoder,
    ZksEncodedNalCallback callback,
    void *opaque
);
uint64_t zks_x264_encoder_embedded_bits(const ZksX264Encoder *encoder);
void zks_x264_encoder_close(ZksX264Encoder *encoder);

#ifdef __cplusplus
}
#endif

#endif
