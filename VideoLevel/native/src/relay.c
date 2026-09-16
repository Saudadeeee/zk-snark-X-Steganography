#include "zkstego_live.h"

#include <stdio.h>

typedef struct {
    ZksAccessUnitAssembler assembler;
    int status;
} RelayContext;

static int write_access_unit(const uint8_t *annexb, size_t size, int is_idr, uint64_t sequence, void *opaque) {
    (void)is_idr;
    (void)sequence;
    (void)opaque;
    if (fwrite(annexb, 1u, size, stdout) != size || fflush(stdout) != 0) {
        return ZKS_ERR_CALLBACK;
    }
    return ZKS_OK;
}

static int consume_nal(const uint8_t *payload, size_t size, void *opaque) {
    RelayContext *context = (RelayContext *)opaque;
    context->status = zks_access_unit_assembler_push(&context->assembler, payload, size);
    return context->status;
}

int main(void) {
    uint8_t input[65536];
    size_t read_count;
    int status = ZKS_OK;
    RelayContext context;
    ZksAnnexBParser parser;
    zks_access_unit_assembler_init(&context.assembler, 1, write_access_unit, NULL);
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
