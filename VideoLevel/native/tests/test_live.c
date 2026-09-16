#include "zkstego_live.h"

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

int main(void) {
    int failed = 0;
    failed |= test_incremental_annexb_parser();
    failed |= test_aud_assembler_emits_complete_idr_access_unit();
    failed |= test_idr_payload_scheduler_is_bounded_and_repeats();
    if (failed) {
        return 1;
    }
    puts("native realtime transport: 3/3 passed");
    return 0;
}
