#include "zkstego_cavlc_direct.h"

#include <limits.h>
#include <string.h>

static unsigned int coefficient_magnitude(int16_t coefficient) {
    if (coefficient < 0) {
        return (unsigned int)(-(int)coefficient);
    }
    return (unsigned int)coefficient;
}

static int find_carrier(
    const int16_t *coefficients,
    size_t coefficient_count,
    size_t *out_index
) {
    size_t index;
    if (!coefficients || !out_index || coefficient_count == 0u) {
        return ZKS_ERR_ARGUMENT;
    }
    for (index = coefficient_count; index > 0u; --index) {
        if (coefficient_magnitude(coefficients[index - 1u]) >= ZKS_CAVLC_MIN_ABS_COEFFICIENT) {
            *out_index = index - 1u;
            return ZKS_OK;
        }
    }
    *out_index = ZKS_CAVLC_NO_INDEX;
    return ZKS_NO_PAYLOAD;
}

static int next_payload_bit(const ZksCavlcEmbedState *state, uint8_t *out_bit) {
    size_t total_bits;
    size_t byte_index;
    unsigned int shift;
    if (!state || !out_bit || !state->payload || state->payload_size == 0u ||
        state->payload_size > SIZE_MAX / 8u) {
        return ZKS_NO_PAYLOAD;
    }
    total_bits = state->payload_size * 8u;
    if (state->next_bit >= total_bits) {
        return ZKS_NO_PAYLOAD;
    }
    byte_index = state->next_bit / 8u;
    shift = 7u - (unsigned int)(state->next_bit % 8u);
    *out_bit = (uint8_t)((state->payload[byte_index] >> shift) & 1u);
    return ZKS_OK;
}

void zks_cavlc_embed_state_init(
    ZksCavlcEmbedState *state,
    const uint8_t *payload,
    size_t payload_size
) {
    if (!state) {
        return;
    }
    memset(state, 0, sizeof(*state));
    state->payload = payload;
    state->payload_size = payload_size;
}

int zks_cavlc_embed_block(
    ZksCavlcEmbedState *state,
    int16_t *coefficients,
    size_t coefficient_count,
    size_t *out_modified_index
) {
    unsigned int magnitude;
    uint8_t bit;
    size_t index;
    int status;
    if (!state || !coefficients || !out_modified_index) {
        return ZKS_ERR_ARGUMENT;
    }
    *out_modified_index = ZKS_CAVLC_NO_INDEX;
    status = next_payload_bit(state, &bit);
    if (status != ZKS_OK) {
        return status;
    }
    status = find_carrier(coefficients, coefficient_count, &index);
    if (status != ZKS_OK) {
        return status;
    }
    magnitude = coefficient_magnitude(coefficients[index]);
    if ((magnitude & 1u) != bit) {
        if (magnitude == (unsigned int)INT16_MAX) {
            return ZKS_NO_PAYLOAD;
        }
        magnitude++;
        coefficients[index] = coefficients[index] < 0 ? -(int16_t)magnitude : (int16_t)magnitude;
        state->modified_coefficients++;
    }
    state->next_bit++;
    state->embedded_bits++;
    *out_modified_index = index;
    return ZKS_OK;
}

int zks_cavlc_extract_block_bit(
    const int16_t *coefficients,
    size_t coefficient_count,
    uint8_t *out_bit,
    size_t *out_carrier_index
) {
    size_t index;
    int status;
    if (!out_bit || !out_carrier_index) {
        return ZKS_ERR_ARGUMENT;
    }
    *out_carrier_index = ZKS_CAVLC_NO_INDEX;
    status = find_carrier(coefficients, coefficient_count, &index);
    if (status != ZKS_OK) {
        return status;
    }
    *out_bit = (uint8_t)(coefficient_magnitude(coefficients[index]) & 1u);
    *out_carrier_index = index;
    return ZKS_OK;
}
