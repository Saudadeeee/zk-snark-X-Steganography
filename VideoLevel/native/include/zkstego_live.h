#ifndef ZKSTEGO_LIVE_H
#define ZKSTEGO_LIVE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    ZKS_OK = 0,
    ZKS_NO_PAYLOAD = 1,
    ZKS_ERR_ARGUMENT = -1,
    ZKS_ERR_MEMORY = -2,
    ZKS_ERR_FORMAT = -3,
    ZKS_ERR_CALLBACK = -4,
};

#define ZKS_MAX_PAYLOAD_CHUNK 256u

typedef int (*ZksNalCallback)(const uint8_t *payload, size_t size, void *opaque);
typedef int (*ZksAccessUnitCallback)(
    const uint8_t *annexb,
    size_t size,
    int is_idr,
    uint64_t sequence,
    void *opaque
);

typedef struct {
    uint8_t *buffer;
    size_t size;
    size_t capacity;
    size_t discarded_prefix_bytes;
    ZksNalCallback callback;
    void *opaque;
} ZksAnnexBParser;

void zks_annexb_parser_init(ZksAnnexBParser *parser, ZksNalCallback callback, void *opaque);
int zks_annexb_parser_feed(ZksAnnexBParser *parser, const uint8_t *data, size_t size);
int zks_annexb_parser_finish(ZksAnnexBParser *parser);
void zks_annexb_parser_destroy(ZksAnnexBParser *parser);

typedef struct {
    uint8_t *prefix;
    size_t prefix_size;
    size_t prefix_capacity;
    uint8_t *current;
    size_t current_size;
    size_t current_capacity;
    int active;
    int current_is_idr;
    int require_aud;
    uint64_t sequence;
    ZksAccessUnitCallback callback;
    void *opaque;
} ZksAccessUnitAssembler;

void zks_access_unit_assembler_init(
    ZksAccessUnitAssembler *assembler,
    int require_aud,
    ZksAccessUnitCallback callback,
    void *opaque
);
int zks_access_unit_assembler_push(
    ZksAccessUnitAssembler *assembler,
    const uint8_t *nal_payload,
    size_t nal_size
);
int zks_access_unit_assembler_finish(ZksAccessUnitAssembler *assembler);
void zks_access_unit_assembler_destroy(ZksAccessUnitAssembler *assembler);

typedef struct {
    uint64_t sequence;
    size_t size;
    uint8_t data[ZKS_MAX_PAYLOAD_CHUNK];
} ZksPayloadChunk;

typedef struct {
    const uint8_t *payload;
    size_t payload_size;
    size_t chunk_size;
    uint32_t repeat_every_idr;
    uint64_t idr_seen;
    uint64_t emitted;
} ZksPayloadScheduler;

void zks_payload_scheduler_init(
    ZksPayloadScheduler *scheduler,
    const uint8_t *payload,
    size_t payload_size,
    size_t chunk_size,
    uint32_t repeat_every_idr
);
int zks_payload_scheduler_next(ZksPayloadScheduler *scheduler, int is_idr, ZksPayloadChunk *out_chunk);

#ifdef __cplusplus
}
#endif

#endif
