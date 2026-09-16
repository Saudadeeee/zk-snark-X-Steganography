#include "zkstego_live.h"

#include <stdlib.h>
#include <string.h>

static int reserve(uint8_t **buffer, size_t *capacity, size_t required) {
    size_t next_capacity;
    uint8_t *next;
    if (required <= *capacity) {
        return ZKS_OK;
    }
    next_capacity = *capacity ? *capacity : 1024u;
    while (next_capacity < required) {
        if (next_capacity > ((size_t)-1) / 2u) {
            return ZKS_ERR_MEMORY;
        }
        next_capacity *= 2u;
    }
    next = (uint8_t *)realloc(*buffer, next_capacity);
    if (!next) {
        return ZKS_ERR_MEMORY;
    }
    *buffer = next;
    *capacity = next_capacity;
    return ZKS_OK;
}

static int append_bytes(uint8_t **buffer, size_t *size, size_t *capacity, const uint8_t *data, size_t data_size) {
    int status;
    if (data_size == 0u) {
        return ZKS_OK;
    }
    status = reserve(buffer, capacity, *size + data_size);
    if (status != ZKS_OK) {
        return status;
    }
    memcpy(*buffer + *size, data, data_size);
    *size += data_size;
    return ZKS_OK;
}

static int find_start_code(const uint8_t *data, size_t size, size_t from, size_t *offset, size_t *length) {
    size_t index;
    for (index = from; index + 3u <= size; ++index) {
        if (index + 4u <= size && data[index] == 0u && data[index + 1u] == 0u &&
            data[index + 2u] == 0u && data[index + 3u] == 1u) {
            *offset = index;
            *length = 4u;
            return 1;
        }
        if (data[index] == 0u && data[index + 1u] == 0u && data[index + 2u] == 1u) {
            *offset = index;
            *length = 3u;
            return 1;
        }
    }
    return 0;
}

void zks_annexb_parser_init(ZksAnnexBParser *parser, ZksNalCallback callback, void *opaque) {
    if (!parser) {
        return;
    }
    memset(parser, 0, sizeof(*parser));
    parser->callback = callback;
    parser->opaque = opaque;
}

static int emit_complete_nals(ZksAnnexBParser *parser) {
    size_t start_offset;
    size_t start_length;
    size_t next_offset;
    size_t next_length;
    int callback_status;
    if (!find_start_code(parser->buffer, parser->size, 0u, &start_offset, &start_length)) {
        if (parser->size > 3u) {
            parser->discarded_prefix_bytes += parser->size - 3u;
            memmove(parser->buffer, parser->buffer + parser->size - 3u, 3u);
            parser->size = 3u;
        }
        return ZKS_OK;
    }
    if (start_offset > 0u) {
        parser->discarded_prefix_bytes += start_offset;
        memmove(parser->buffer, parser->buffer + start_offset, parser->size - start_offset);
        parser->size -= start_offset;
    }
    while (find_start_code(parser->buffer, parser->size, 0u, &start_offset, &start_length) &&
           find_start_code(parser->buffer, parser->size, start_offset + start_length, &next_offset, &next_length)) {
        (void)next_length;
        if (next_offset > start_offset + start_length && parser->callback) {
            callback_status = parser->callback(
                parser->buffer + start_offset + start_length,
                next_offset - start_offset - start_length,
                parser->opaque
            );
            if (callback_status != ZKS_OK) {
                return ZKS_ERR_CALLBACK;
            }
        }
        memmove(parser->buffer, parser->buffer + next_offset, parser->size - next_offset);
        parser->size -= next_offset;
    }
    return ZKS_OK;
}

int zks_annexb_parser_feed(ZksAnnexBParser *parser, const uint8_t *data, size_t size) {
    int status;
    if (!parser || (!data && size != 0u)) {
        return ZKS_ERR_ARGUMENT;
    }
    status = append_bytes(&parser->buffer, &parser->size, &parser->capacity, data, size);
    if (status != ZKS_OK) {
        return status;
    }
    return emit_complete_nals(parser);
}

int zks_annexb_parser_finish(ZksAnnexBParser *parser) {
    size_t start_offset;
    size_t start_length;
    int callback_status;
    if (!parser) {
        return ZKS_ERR_ARGUMENT;
    }
    if (!find_start_code(parser->buffer, parser->size, 0u, &start_offset, &start_length)) {
        parser->discarded_prefix_bytes += parser->size;
        parser->size = 0u;
        return ZKS_OK;
    }
    if (parser->size > start_offset + start_length && parser->callback) {
        callback_status = parser->callback(
            parser->buffer + start_offset + start_length,
            parser->size - start_offset - start_length,
            parser->opaque
        );
        if (callback_status != ZKS_OK) {
            return ZKS_ERR_CALLBACK;
        }
    }
    parser->size = 0u;
    return ZKS_OK;
}

void zks_annexb_parser_destroy(ZksAnnexBParser *parser) {
    if (!parser) {
        return;
    }
    free(parser->buffer);
    memset(parser, 0, sizeof(*parser));
}

static int append_annexb_nal(uint8_t **buffer, size_t *size, size_t *capacity, const uint8_t *payload, size_t payload_size) {
    static const uint8_t start_code[] = {0u, 0u, 0u, 1u};
    int status = append_bytes(buffer, size, capacity, start_code, sizeof(start_code));
    if (status != ZKS_OK) {
        return status;
    }
    return append_bytes(buffer, size, capacity, payload, payload_size);
}

void zks_access_unit_assembler_init(
    ZksAccessUnitAssembler *assembler,
    int require_aud,
    ZksAccessUnitCallback callback,
    void *opaque
) {
    if (!assembler) {
        return;
    }
    memset(assembler, 0, sizeof(*assembler));
    assembler->require_aud = require_aud ? 1 : 0;
    assembler->callback = callback;
    assembler->opaque = opaque;
}

static int emit_access_unit(ZksAccessUnitAssembler *assembler) {
    int callback_status;
    if (!assembler->active || assembler->current_size == 0u) {
        return ZKS_OK;
    }
    if (assembler->callback) {
        callback_status = assembler->callback(
            assembler->current,
            assembler->current_size,
            assembler->current_is_idr,
            assembler->sequence,
            assembler->opaque
        );
        if (callback_status != ZKS_OK) {
            return ZKS_ERR_CALLBACK;
        }
    }
    assembler->sequence++;
    assembler->current_size = 0u;
    assembler->active = 0;
    assembler->current_is_idr = 0;
    return ZKS_OK;
}

int zks_access_unit_assembler_push(
    ZksAccessUnitAssembler *assembler,
    const uint8_t *nal_payload,
    size_t nal_size
) {
    uint8_t nal_type;
    int status;
    if (!assembler || !nal_payload || nal_size == 0u) {
        return ZKS_ERR_ARGUMENT;
    }
    nal_type = (uint8_t)(nal_payload[0] & 0x1fu);
    if (nal_type == 9u) {
        status = emit_access_unit(assembler);
        if (status != ZKS_OK) {
            return status;
        }
        assembler->active = 1;
        status = append_bytes(
            &assembler->current, &assembler->current_size, &assembler->current_capacity,
            assembler->prefix, assembler->prefix_size
        );
        if (status != ZKS_OK) {
            return status;
        }
        assembler->prefix_size = 0u;
        return append_annexb_nal(
            &assembler->current, &assembler->current_size, &assembler->current_capacity,
            nal_payload, nal_size
        );
    }
    if (!assembler->active) {
        if (nal_type == 6u || nal_type == 7u || nal_type == 8u) {
            return append_annexb_nal(
                &assembler->prefix, &assembler->prefix_size, &assembler->prefix_capacity,
                nal_payload, nal_size
            );
        }
        if (assembler->require_aud) {
            return ZKS_ERR_FORMAT;
        }
        assembler->active = 1;
        status = append_bytes(
            &assembler->current, &assembler->current_size, &assembler->current_capacity,
            assembler->prefix, assembler->prefix_size
        );
        if (status != ZKS_OK) {
            return status;
        }
        assembler->prefix_size = 0u;
    }
    if (nal_type == 5u) {
        assembler->current_is_idr = 1;
    }
    return append_annexb_nal(
        &assembler->current, &assembler->current_size, &assembler->current_capacity,
        nal_payload, nal_size
    );
}

int zks_access_unit_assembler_finish(ZksAccessUnitAssembler *assembler) {
    if (!assembler) {
        return ZKS_ERR_ARGUMENT;
    }
    return emit_access_unit(assembler);
}

void zks_access_unit_assembler_destroy(ZksAccessUnitAssembler *assembler) {
    if (!assembler) {
        return;
    }
    free(assembler->prefix);
    free(assembler->current);
    memset(assembler, 0, sizeof(*assembler));
}

void zks_payload_scheduler_init(
    ZksPayloadScheduler *scheduler,
    const uint8_t *payload,
    size_t payload_size,
    size_t chunk_size,
    uint32_t repeat_every_idr
) {
    if (!scheduler) {
        return;
    }
    memset(scheduler, 0, sizeof(*scheduler));
    scheduler->payload = payload;
    scheduler->payload_size = payload_size;
    scheduler->chunk_size = chunk_size;
    scheduler->repeat_every_idr = repeat_every_idr;
}

int zks_payload_scheduler_next(ZksPayloadScheduler *scheduler, int is_idr, ZksPayloadChunk *out_chunk) {
    size_t offset;
    size_t index;
    if (!scheduler || !out_chunk || !scheduler->payload || scheduler->payload_size == 0u ||
        scheduler->chunk_size == 0u || scheduler->chunk_size > ZKS_MAX_PAYLOAD_CHUNK ||
        scheduler->repeat_every_idr == 0u) {
        return ZKS_ERR_ARGUMENT;
    }
    if (!is_idr) {
        return ZKS_NO_PAYLOAD;
    }
    scheduler->idr_seen++;
    if (((scheduler->idr_seen - 1u) % scheduler->repeat_every_idr) != 0u) {
        return ZKS_NO_PAYLOAD;
    }
    offset = (size_t)((scheduler->emitted * scheduler->chunk_size) % scheduler->payload_size);
    out_chunk->sequence = scheduler->emitted;
    out_chunk->size = scheduler->chunk_size;
    for (index = 0u; index < scheduler->chunk_size; ++index) {
        out_chunk->data[index] = scheduler->payload[(offset + index) % scheduler->payload_size];
    }
    scheduler->emitted++;
    return ZKS_OK;
}
