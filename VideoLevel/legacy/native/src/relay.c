#include "zkstego_live.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

static const uint8_t ZKS_DEFAULT_UUID[16] = {
    0x9d, 0x4f, 0x11, 0x0d, 0x48, 0xfe, 0x45, 0x20,
    0x9d, 0xfe, 0x01, 0x57, 0x91, 0x82, 0x45, 0x72,
};

typedef struct {
    ZksAccessUnitAssembler assembler;
    ZksPayloadScheduler scheduler;
    int inject_sei;
    int status;
} RelayContext;

static int hex_digit(char character) {
    if (character >= '0' && character <= '9') {
        return character - '0';
    }
    character = (char)tolower((unsigned char)character);
    if (character >= 'a' && character <= 'f') {
        return 10 + character - 'a';
    }
    return -1;
}

static int parse_hex_payload(const char *text, uint8_t *output, size_t *output_size) {
    size_t length;
    size_t index;
    if (!text || !output || !output_size) {
        return ZKS_ERR_ARGUMENT;
    }
    length = strlen(text);
    if ((length & 1u) != 0u || length == 0u || length / 2u > ZKS_MAX_PAYLOAD_CHUNK) {
        return ZKS_ERR_ARGUMENT;
    }
    for (index = 0u; index < length / 2u; ++index) {
        int high = hex_digit(text[index * 2u]);
        int low = hex_digit(text[index * 2u + 1u]);
        if (high < 0 || low < 0) {
            return ZKS_ERR_ARGUMENT;
        }
        output[index] = (uint8_t)((high << 4u) | low);
    }
    *output_size = length / 2u;
    return ZKS_OK;
}

static int write_access_unit(const uint8_t *annexb, size_t size, int is_idr, uint64_t sequence, void *opaque) {
    RelayContext *context = (RelayContext *)opaque;
    const uint8_t *output = annexb;
    size_t output_size = size;
    ZksByteBuffer injected;
    ZksPayloadChunk chunk;
    int status;
    (void)sequence;
    zks_byte_buffer_init(&injected);
    if (context->inject_sei) {
        status = zks_payload_scheduler_next(&context->scheduler, is_idr, &chunk);
        if (status == ZKS_OK) {
            status = zks_sei_inject_user_data(annexb, size, ZKS_DEFAULT_UUID, &chunk, &injected);
            if (status != ZKS_OK) {
                zks_byte_buffer_destroy(&injected);
                return status;
            }
            output = injected.data;
            output_size = injected.size;
        } else if (status != ZKS_NO_PAYLOAD) {
            zks_byte_buffer_destroy(&injected);
            return status;
        }
    }
    if (fwrite(output, 1u, output_size, stdout) != output_size || fflush(stdout) != 0) {
        zks_byte_buffer_destroy(&injected);
        return ZKS_ERR_CALLBACK;
    }
    zks_byte_buffer_destroy(&injected);
    return ZKS_OK;
}

static int consume_nal(const uint8_t *payload, size_t size, void *opaque) {
    RelayContext *context = (RelayContext *)opaque;
    context->status = zks_access_unit_assembler_push(&context->assembler, payload, size);
    return context->status;
}

int main(int argc, char **argv) {
    uint8_t input[65536];
    uint8_t payload[ZKS_MAX_PAYLOAD_CHUNK];
    size_t payload_size = 0u;
    size_t chunk_size = 32u;
    size_t read_count;
    int argument_index;
    int status = ZKS_OK;
    RelayContext context;
    ZksAnnexBParser parser;
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) {
        fprintf(stderr, "cannot set binary stdin/stdout mode\n");
        return 1;
    }
#endif
    memset(&context, 0, sizeof(context));
    for (argument_index = 1; argument_index < argc; ++argument_index) {
        if (strcmp(argv[argument_index], "--sei-payload-hex") == 0 && argument_index + 1 < argc) {
            status = parse_hex_payload(argv[++argument_index], payload, &payload_size);
            if (status != ZKS_OK) {
                fprintf(stderr, "invalid --sei-payload-hex (1..256 bytes as even-length hex required)\n");
                return 2;
            }
            context.inject_sei = 1;
        } else if (strcmp(argv[argument_index], "--chunk-bytes") == 0 && argument_index + 1 < argc) {
            char *end = NULL;
            unsigned long value = strtoul(argv[++argument_index], &end, 10);
            if (!end || *end != '\0' || value == 0u || value > ZKS_MAX_PAYLOAD_CHUNK) {
                fprintf(stderr, "invalid --chunk-bytes (1..256 required)\n");
                return 2;
            }
            chunk_size = (size_t)value;
        } else {
            fprintf(stderr, "usage: zkstego_annexb_relay [--sei-payload-hex HEX] [--chunk-bytes 1..256]\n");
            return 2;
        }
    }
    if (context.inject_sei) {
        zks_payload_scheduler_init(&context.scheduler, payload, payload_size, chunk_size, 1u);
    }
    zks_access_unit_assembler_init(&context.assembler, 1, write_access_unit, &context);
    context.status = ZKS_OK;
    zks_annexb_parser_init(&parser, consume_nal, &context);
    while ((read_count = fread(input, 1u, sizeof(input), stdin)) > 0u) {
        status = zks_annexb_parser_feed(&parser, input, read_count);
        if (status != ZKS_OK) {
            break;
        }
    }
    if (ferror(stdin)) {
        status = ZKS_ERR_FORMAT;
    }
    if (status == ZKS_OK) {
        status = zks_annexb_parser_finish(&parser);
    }
    if (status == ZKS_OK) {
        status = zks_access_unit_assembler_finish(&context.assembler);
    }
    zks_annexb_parser_destroy(&parser);
    zks_access_unit_assembler_destroy(&context.assembler);
    return status == ZKS_OK ? 0 : 1;
}
