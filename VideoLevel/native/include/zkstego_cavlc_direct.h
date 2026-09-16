#ifndef ZKSTEGO_CAVLC_DIRECT_H
#define ZKSTEGO_CAVLC_DIRECT_H

#include <stddef.h>
#include <stdint.h>

#include "zkstego_live.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * This carrier operates on quantized transform coefficients before CAVLC
 * serializes them. It is deliberately constrained to one high-frequency AC
 * coefficient per 4x4 block and never turns a non-zero coefficient into zero.
 */
#define ZKS_CAVLC_MIN_ABS_COEFFICIENT 4
#define ZKS_CAVLC_NO_INDEX ((size_t)-1)

typedef struct {
    const uint8_t *payload;
    size_t payload_size;
    size_t next_bit;
    uint64_t embedded_bits;
    uint64_t modified_coefficients;
} ZksCavlcEmbedState;

void zks_cavlc_embed_state_init(
    ZksCavlcEmbedState *state,
    const uint8_t *payload,
    size_t payload_size
);

/*
 * Selects the highest-frequency eligible coefficient in scan order and embeds
 * one payload bit in its magnitude parity. Returns ZKS_NO_PAYLOAD when the
 * payload is exhausted or no coefficient satisfies the safety threshold.
 */
int zks_cavlc_embed_block(
    ZksCavlcEmbedState *state,
    int16_t *coefficients,
    size_t coefficient_count,
    size_t *out_modified_index
);

/* Reads the bit using exactly the selection rule used by the embedder. */
int zks_cavlc_extract_block_bit(
    const int16_t *coefficients,
    size_t coefficient_count,
    uint8_t *out_bit,
    size_t *out_carrier_index
);

#ifdef __cplusplus
}
#endif

#endif
