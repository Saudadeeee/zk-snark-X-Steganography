#include "zkstego_x264.h"

#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

typedef struct {
    FILE *output;
    size_t bytes_written;
    size_t nal_count;
} OutputState;

static int parse_positive(const char *text, int *value)
{
    char *end = NULL;
    long parsed;
    errno = 0;
    parsed = strtol(text, &end, 10);
    if (errno || !end || *end || parsed <= 0 || parsed > INT_MAX)
        return 0;
    *value = (int)parsed;
    return 1;
}

static int parse_header(char *header, int *width, int *height, int *fps_num, int *fps_den)
{
    char *token;
    int chroma_420 = 1;
    if (strncmp(header, "YUV4MPEG2 ", 10u) != 0)
        return 0;
    token = strtok(header + 10, " \r\n");
    while (token)
    {
        if (token[0] == 'W')
        {
            if (!parse_positive(token + 1, width))
                return 0;
        }
        else if (token[0] == 'H')
        {
            if (!parse_positive(token + 1, height))
                return 0;
        }
        else if (token[0] == 'F')
        {
            char *separator = strchr(token + 1, ':');
            if (!separator)
                return 0;
            *separator = '\0';
            if (!parse_positive(token + 1, fps_num) ||
                !parse_positive(separator + 1, fps_den))
                return 0;
        }
        else if (token[0] == 'C')
        {
            chroma_420 = strncmp(token, "C420", 4u) == 0;
        }
        token = strtok(NULL, " \r\n");
    }
    return *width > 0 && *height > 0 && !(*width & 1) && !(*height & 1) &&
           *fps_num > 0 && *fps_den > 0 && chroma_420;
}

static int decode_hex(const char *hex, uint8_t **bytes, size_t *length)
{
    size_t index;
    size_t hex_length = strlen(hex);
    uint8_t *decoded;
    if (!hex_length || (hex_length & 1u) || hex_length / 2u > (size_t)(INT_MAX / 8))
        return 0;
    decoded = (uint8_t *)malloc(hex_length / 2u);
    if (!decoded)
        return 0;
    for (index = 0; index < hex_length; index += 2u)
    {
        int high;
        int low;
        char high_char = hex[index];
        char low_char = hex[index + 1u];
        high = high_char >= '0' && high_char <= '9' ? high_char - '0' :
               high_char >= 'a' && high_char <= 'f' ? high_char - 'a' + 10 :
               high_char >= 'A' && high_char <= 'F' ? high_char - 'A' + 10 : -1;
        low = low_char >= '0' && low_char <= '9' ? low_char - '0' :
              low_char >= 'a' && low_char <= 'f' ? low_char - 'a' + 10 :
              low_char >= 'A' && low_char <= 'F' ? low_char - 'A' + 10 : -1;
        if (high < 0 || low < 0)
        {
            free(decoded);
            return 0;
        }
        decoded[index / 2u] = (uint8_t)((high << 4) | low);
    }
    *bytes = decoded;
    *length = hex_length / 2u;
    return 1;
}

static int read_payload_file(const char *path, uint8_t **bytes, size_t *length)
{
    FILE *file;
    long file_size;
    uint8_t *data;
    size_t data_size;
    int extra_byte;
    int read_failed;
    int close_failed;
    if (!path || !bytes || !length)
        return 0;
    file = fopen(path, "rb");
    if (!file)
        return 0;
    if (fseek(file, 0, SEEK_END) != 0 || (file_size = ftell(file)) <= 0 ||
        (unsigned long)file_size > (unsigned long)(INT_MAX / 8) ||
        fseek(file, 0, SEEK_SET) != 0)
    {
        fclose(file);
        return 0;
    }
    data_size = (size_t)file_size;
    data = (uint8_t *)malloc(data_size);
    if (!data)
    {
        fclose(file);
        return 0;
    }
    if (fread(data, 1u, data_size, file) != data_size || ferror(file))
    {
        free(data);
        fclose(file);
        return 0;
    }
    extra_byte = fgetc(file);
    read_failed = extra_byte != EOF || ferror(file);
    close_failed = fclose(file) != 0;
    if (read_failed || close_failed)
    {
        free(data);
        return 0;
    }
    *bytes = data;
    *length = data_size;
    return 1;
}

static int contains_sei_nal(const uint8_t *annexb, size_t size)
{
    size_t header_offset;
    if (size >= 5u && annexb[0] == 0u && annexb[1] == 0u && annexb[2] == 0u && annexb[3] == 1u)
        header_offset = 4u;
    else if (size >= 4u && annexb[0] == 0u && annexb[1] == 0u && annexb[2] == 1u)
        header_offset = 3u;
    else
        return 1;
    return (annexb[header_offset] & 0x1fu) == 6u;
}

static int write_nal(const uint8_t *annexb, size_t size, void *opaque)
{
    OutputState *state = (OutputState *)opaque;
    if (!annexb || !size || !state || !state->output || contains_sei_nal(annexb, size))
        return ZKS_ERR_FORMAT;
    if (fwrite(annexb, 1u, size, state->output) != size)
        return ZKS_ERR_FORMAT;
    state->bytes_written += size;
    ++state->nal_count;
    return ZKS_OK;
}

static int publish_output(const char *temporary_path, const char *output_path)
{
#ifdef _WIN32
    return MoveFileExA(temporary_path, output_path,
                       MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
#else
    return rename(temporary_path, output_path) == 0;
#endif
}

static void usage(const char *program)
{
    fprintf(stderr,
            "usage: %s --input-y4m cover.y4m --output stego.h264 "
            "(--payload-hex HEX | --payload-file PATH)\n"
            "Input must be progressive YUV4MPEG2 C420; payload is embedded in-band.\n",
            program);
}

int main(int argc, char **argv)
{
    const char *input_path = NULL;
    const char *output_path = NULL;
    const char *payload_hex = NULL;
    const char *payload_file_path = NULL;
    char header[4096];
    char frame_header[4096];
    char *temporary_path = NULL;
    uint8_t *payload = NULL;
    uint8_t *frame = NULL;
    size_t payload_size = 0u;
    size_t y_size;
    size_t chroma_size;
    size_t frame_size;
    size_t output_path_length;
    size_t frame_count = 0u;
    int width = 0;
    int height = 0;
    int fps_num = 0;
    int fps_den = 0;
    int status = EXIT_FAILURE;
    int arg;
    FILE *input = NULL;
    FILE *output = NULL;
    ZksX264Config config = { 0 };
    ZksX264Encoder *encoder = NULL;
    OutputState output_state = { 0 };

    if (argc < 7 || !(argc & 1))
    {
        usage(argv[0]);
        return EXIT_FAILURE;
    }
    for (arg = 1; arg < argc; arg += 2)
    {
        if (strcmp(argv[arg], "--input-y4m") == 0 && !input_path)
            input_path = argv[arg + 1];
        else if (strcmp(argv[arg], "--output") == 0 && !output_path)
            output_path = argv[arg + 1];
        else if (strcmp(argv[arg], "--payload-hex") == 0 && !payload_hex)
            payload_hex = argv[arg + 1];
        else if (strcmp(argv[arg], "--payload-file") == 0 && !payload_file_path)
            payload_file_path = argv[arg + 1];
        else
        {
            usage(argv[0]);
            return EXIT_FAILURE;
        }
    }
    if (!input_path || !output_path || (!!payload_hex == !!payload_file_path) ||
        !(payload_file_path ?
          read_payload_file(payload_file_path, &payload, &payload_size) :
          decode_hex(payload_hex, &payload, &payload_size)))
    {
        usage(argv[0]);
        goto cleanup;
    }
    input = fopen(input_path, "rb");
    if (!input || !fgets(header, sizeof(header), input) ||
        !parse_header(header, &width, &height, &fps_num, &fps_den))
    {
        fprintf(stderr, "invalid or unsupported Y4M header (requires 4:2:0 and even dimensions)\n");
        goto cleanup;
    }
    if ((size_t)width > SIZE_MAX / (size_t)height)
        goto cleanup;
    y_size = (size_t)width * (size_t)height;
    chroma_size = y_size / 4u;
    if (y_size > SIZE_MAX - 2u * chroma_size)
        goto cleanup;
    frame_size = y_size + 2u * chroma_size;
    frame = (uint8_t *)malloc(frame_size);
    output_path_length = strlen(output_path);
    if (!frame || output_path_length > SIZE_MAX - 9u)
        goto cleanup;
    temporary_path = (char *)malloc(output_path_length + 9u);
    if (!temporary_path)
        goto cleanup;
    memcpy(temporary_path, output_path, output_path_length);
    memcpy(temporary_path + output_path_length, ".partial", 9u);
    output = fopen(temporary_path, "wb");
    if (!output)
    {
        fprintf(stderr, "cannot create temporary output file\n");
        goto cleanup;
    }
    output_state.output = output;
    config.width = width;
    config.height = height;
    config.fps_num = fps_num;
    config.fps_den = fps_den;
    config.keyint = 30;
    config.crf = 23;
    config.direct_payload = payload;
    config.direct_payload_size = payload_size;
    if (zks_x264_encoder_open(&config, &encoder) != ZKS_OK)
    {
        fprintf(stderr, "x264 direct-CAVLC encoder rejected this profile\n");
        goto cleanup;
    }
    while (fgets(frame_header, sizeof(frame_header), input))
    {
        if (strncmp(frame_header, "FRAME", 5u) != 0)
        {
            fprintf(stderr, "invalid Y4M frame marker at frame %zu\n", frame_count);
            goto cleanup;
        }
        if (fread(frame, 1u, frame_size, input) != frame_size)
        {
            fprintf(stderr, "truncated Y4M frame %zu\n", frame_count);
            goto cleanup;
        }
        if (zks_x264_encoder_encode_i420(
                encoder,
                frame, width,
                frame + y_size, width / 2,
                frame + y_size + chroma_size, width / 2,
                (int64_t)frame_count,
                write_nal,
                &output_state) != ZKS_OK)
        {
            fprintf(stderr, "encoding failed at frame %zu\n", frame_count);
            goto cleanup;
        }
        ++frame_count;
    }
    if (ferror(input) || !frame_count)
    {
        fprintf(stderr, "empty or unreadable Y4M frame stream\n");
        goto cleanup;
    }
    if (zks_x264_encoder_finish(encoder, write_nal, &output_state) != ZKS_OK)
    {
        fprintf(stderr, "payload capacity insufficient: embedded %llu of %zu bits\n",
                (unsigned long long)zks_x264_encoder_embedded_bits(encoder), payload_size * 8u);
        goto cleanup;
    }
    if (fflush(output) != 0 || ferror(output) || fclose(output) != 0)
    {
        output = NULL;
        fprintf(stderr, "failed to flush encoded output\n");
        goto cleanup;
    }
    output = NULL;
    if (!output_state.bytes_written || !publish_output(temporary_path, output_path))
    {
        fprintf(stderr, "failed to atomically publish encoded output\n");
        goto cleanup;
    }
    printf("PASS frames=%zu dimensions=%dx%d embedded_bits=%llu bytes=%zu nals=%zu\n",
           frame_count, width, height,
           (unsigned long long)zks_x264_encoder_embedded_bits(encoder),
           output_state.bytes_written, output_state.nal_count);
    status = EXIT_SUCCESS;

cleanup:
    if (output)
        fclose(output);
    if (status != EXIT_SUCCESS && temporary_path)
        remove(temporary_path);
    if (input)
        fclose(input);
    zks_x264_encoder_close(encoder);
    free(frame);
    free(payload);
    free(temporary_path);
    return status;
}
