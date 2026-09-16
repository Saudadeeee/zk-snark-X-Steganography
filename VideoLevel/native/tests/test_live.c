#include "zkstego_live.h"
#include "zkstego_cavlc_direct.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__, #condition); \
        return 1; \
    } \
} while (0)

typedef struct {
    uint8_t types[16];
    size_t count;
} NalCollector;

static int collect_nal(const uint8_t *payload, size_t size, void *opaque) {
    NalCollector *collector = (NalCollector *)opaque;
    if (size == 0 || collector->count >= 16) {
        return ZKS_ERR_ARGUMENT;
    }
    collector->types[collector->count++] = (uint8_t)(payload[0] & 0x1f);
    return ZKS_OK;
}

typedef struct {
    size_t count;
    int idr[4];
    size_t sizes[4];
} AuCollector;

typedef struct {
    size_t count;
    ZksPayloadChunk chunk;
} ChunkCollector;

static int collect_chunk(const ZksPayloadChunk *chunk, void *opaque) {
    ChunkCollector *collector = (ChunkCollector *)opaque;
    CHECK(collector->count == 0);
    collector->chunk = *chunk;
    collector->count++;
    return ZKS_OK;
}

static int collect_au(const uint8_t *annexb, size_t size, int is_idr, uint64_t sequence, void *opaque) {
    AuCollector *collector = (AuCollector *)opaque;
    (void)annexb;
    CHECK(sequence == collector->count);
    CHECK(collector->count < 4);
    collector->idr[collector->count] = is_idr;
    collector->sizes[collector->count] = size;
    collector->count++;
    return ZKS_OK;
}

static int test_incremental_annexb_parser(void) {
    static const uint8_t stream[] = {
        0, 0, 0, 1, 0x67, 1,
        0, 0, 1, 0x68, 2,
        0, 0, 0, 1, 0x69, 3,
        0, 0, 0, 1, 0x65, 4,
    };
    ZksAnnexBParser parser;
    NalCollector collector = {{0}, 0};
    zks_annexb_parser_init(&parser, collect_nal, &collector);
    CHECK(zks_annexb_parser_feed(&parser, stream, 3) == ZKS_OK);
    CHECK(zks_annexb_parser_feed(&parser, stream + 3, 7) == ZKS_OK);
    CHECK(zks_annexb_parser_feed(&parser, stream + 10, sizeof(stream) - 10) == ZKS_OK);
    CHECK(zks_annexb_parser_finish(&parser) == ZKS_OK);
    zks_annexb_parser_destroy(&parser);
    CHECK(collector.count == 4);
    CHECK(collector.types[0] == 7 && collector.types[1] == 8);
    CHECK(collector.types[2] == 9 && collector.types[3] == 5);
    return 0;
}

static int test_aud_assembler_emits_complete_idr_access_unit(void) {
    static const uint8_t aud[] = {0x69, 0xf0};
    static const uint8_t idr[] = {0x65, 0xaa};
    static const uint8_t p[] = {0x61, 0xbb};
    ZksAccessUnitAssembler assembler;
    AuCollector collector = {0};
    zks_access_unit_assembler_init(&assembler, 1, collect_au, &collector);
    CHECK(zks_access_unit_assembler_push(&assembler, aud, sizeof(aud)) == ZKS_OK);
    CHECK(zks_access_unit_assembler_push(&assembler, idr, sizeof(idr)) == ZKS_OK);
    CHECK(zks_access_unit_assembler_push(&assembler, aud, sizeof(aud)) == ZKS_OK);
    CHECK(zks_access_unit_assembler_push(&assembler, p, sizeof(p)) == ZKS_OK);
    CHECK(zks_access_unit_assembler_finish(&assembler) == ZKS_OK);
    zks_access_unit_assembler_destroy(&assembler);
    CHECK(collector.count == 2);
    CHECK(collector.idr[0] == 1 && collector.idr[1] == 0);
    return 0;
}

static int test_idr_payload_scheduler_is_bounded_and_repeats(void) {
    static const uint8_t payload[] = {'p', 'a', 'y'};
    ZksPayloadScheduler scheduler;
    ZksPayloadChunk chunk;
    zks_payload_scheduler_init(&scheduler, payload, sizeof(payload), 2, 1);
    CHECK(zks_payload_scheduler_next(&scheduler, 0, &chunk) == ZKS_NO_PAYLOAD);
    CHECK(zks_payload_scheduler_next(&scheduler, 1, &chunk) == ZKS_OK);
    CHECK(chunk.sequence == 0 && chunk.size == 2 && memcmp(chunk.data, "pa", 2) == 0);
    CHECK(zks_payload_scheduler_next(&scheduler, 1, &chunk) == ZKS_OK);
    CHECK(chunk.sequence == 1 && chunk.size == 2 && memcmp(chunk.data, "yp", 2) == 0);
    return 0;
}

static int test_inband_sei_round_trip_preserves_video_nals(void) {
    static const uint8_t access_unit[] = {
        0, 0, 0, 1, 0x69, 0xf0,
        0, 0, 0, 1, 0x65, 0xaa,
    };
    static const uint8_t uuid[16] = {
        0x9d, 0x4f, 0x11, 0x0d, 0x48, 0xfe, 0x45, 0x20,
        0x9d, 0xfe, 0x01, 0x57, 0x91, 0x82, 0x45, 0x72,
    };
    ZksPayloadChunk chunk = {7u, 3u, {0u, 0u, 1u}};
    ZksByteBuffer output;
    ZksAnnexBParser parser;
    NalCollector nal_collector = {{0}, 0};
    ChunkCollector chunk_collector = {0};

    zks_byte_buffer_init(&output);
    CHECK(zks_sei_inject_user_data(access_unit, sizeof(access_unit), uuid, &chunk, &output) == ZKS_OK);
    zks_annexb_parser_init(&parser, collect_nal, &nal_collector);
    CHECK(zks_annexb_parser_feed(&parser, output.data, output.size) == ZKS_OK);
    CHECK(zks_annexb_parser_finish(&parser) == ZKS_OK);
    zks_annexb_parser_destroy(&parser);
    CHECK(nal_collector.count == 3);
    CHECK(nal_collector.types[0] == 9 && nal_collector.types[1] == 6 && nal_collector.types[2] == 5);
    CHECK(zks_sei_extract_user_data(output.data, output.size, uuid, collect_chunk, &chunk_collector) == ZKS_OK);
    CHECK(chunk_collector.count == 1);
    CHECK(chunk_collector.chunk.sequence == 7u && chunk_collector.chunk.size == 3u);
    CHECK(memcmp(chunk_collector.chunk.data, chunk.data, chunk.size) == 0);
    zks_byte_buffer_destroy(&output);
    return 0;
}

static int test_direct_cavlc_embedding_preserves_nonzero_support(void) {
    int16_t coefficients[16] = {
        0, 0, 1, 0,
        0, -2, 0, 0,
        0, 0, 0, 3,
        0, 0, 0, -6,
    };
    static const uint8_t payload[] = {0x40u}; /* First payload bit is one. */
    ZksCavlcEmbedState state;
    size_t modified_index = 0u;

    zks_cavlc_embed_state_init(&state, payload, sizeof(payload));
    CHECK(zks_cavlc_embed_block(&state, coefficients, 16u, &modified_index) == ZKS_OK);
    CHECK(modified_index == 15u);
    CHECK(coefficients[15] == -7);
    CHECK(coefficients[2] == 1 && coefficients[5] == -2 && coefficients[11] == 3);
    CHECK(state.embedded_bits == 1u && state.modified_coefficients == 1u);
    return 0;
}

static int test_direct_cavlc_embedding_rejects_unsafe_block_without_consuming_payload(void) {
    int16_t coefficients[16] = {
        0, 0, 1, 0,
        0, -2, 0, 0,
        0, 0, 0, 2,
        0, 0, 0, -1,
    };
    static const uint8_t payload[] = {0x80u};
    ZksCavlcEmbedState state;
    size_t modified_index = 0u;

    zks_cavlc_embed_state_init(&state, payload, sizeof(payload));
    CHECK(zks_cavlc_embed_block(&state, coefficients, 16u, &modified_index) == ZKS_NO_PAYLOAD);
    CHECK(modified_index == ZKS_CAVLC_NO_INDEX);
    CHECK(coefficients[11] == 2 && coefficients[15] == -1);
    CHECK(state.embedded_bits == 0u && state.modified_coefficients == 0u);
    return 0;
}

static int test_direct_cavlc_extraction_uses_same_high_frequency_carrier(void) {
    int16_t coefficients[16] = {
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 4,
        0, 0, 0, -7,
    };
    uint8_t bit = 0u;
    size_t carrier_index = 0u;

    CHECK(zks_cavlc_extract_block_bit(coefficients, 16u, &bit, &carrier_index) == ZKS_OK);
    CHECK(carrier_index == 15u && bit == 1u);
    return 0;
}

int main(void) {
    int failed = 0;
    failed |= test_incremental_annexb_parser();
    failed |= test_aud_assembler_emits_complete_idr_access_unit();
    failed |= test_idr_payload_scheduler_is_bounded_and_repeats();
    failed |= test_inband_sei_round_trip_preserves_video_nals();
    failed |= test_direct_cavlc_embedding_preserves_nonzero_support();
    failed |= test_direct_cavlc_embedding_rejects_unsafe_block_without_consuming_payload();
    failed |= test_direct_cavlc_extraction_uses_same_high_frequency_carrier();
    if (failed) {
        return 1;
    }
    puts("native realtime transport: 7/7 passed");
    return 0;
}
