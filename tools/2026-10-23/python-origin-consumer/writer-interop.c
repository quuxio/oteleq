#define _POSIX_C_SOURCE 200809L
#include "InputJournal.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CHECK(condition) do { if (!(condition)) _exit(70); } while (0)

static unsigned char *input(const char *path, size_t *size, struct stat *metadata) {
    int fd = open(path, O_RDONLY);
    CHECK(fd >= 0 && fstat(fd, metadata) == 0 && S_ISREG(metadata->st_mode));
    CHECK(metadata->st_size >= 0 && metadata->st_size <= OTELC_PY_SOURCE_LIMIT);
    *size = (size_t)metadata->st_size;
    unsigned char *bytes = malloc(*size + 1);
    CHECK(bytes != NULL);
    size_t used = 0;
    while (used < *size) {
        ssize_t result = read(fd, bytes + used, *size - used);
        if (result < 0 && errno == EINTR) continue;
        CHECK(result > 0);
        used += (size_t)result;
    }
    CHECK(close(fd) == 0);
    return bytes;
}

int main(int argc, char **argv) {
    CHECK(argc == 6);
    int loader = strstr(argv[5], "loader") != NULL;
    int sdk = strstr(argv[5], "on") != NULL;
    struct stat source_stat, root_stat, code_stat;
    size_t source_size, root_size, code_size;
    unsigned char *source = input(argv[2], &source_size, &source_stat);
    unsigned char *root = input(argv[3], &root_size, &root_stat);
    unsigned char *code = input(argv[4], &code_size, &code_stat);
    int fd = open(argv[1], O_WRONLY | O_CREAT | O_EXCL, 0600);
    CHECK(fd >= 0 && otelc_py_journal_open_version(fd, 2) == 0);
    uint64_t token = 0;
    if (loader) {
        CHECK(otelc_py_journal_import_event(argv[2], source, source_size, &source_stat, &token) == 0);
    } else {
        CHECK(otelc_py_journal_source_event(argv[2], source, source_size, &source_stat, &token) == 0);
    }
    CHECK(token == 1);
    uint64_t root_fields[] = {77, 90, loader ? 12 : 0, token, loader ? 2 : 1, 0x030c0ff0, 2, 0, 0};
    CHECK(otelc_py_journal_origin(5, argv[2], root, root_size, root_fields, 9) == 0);
    uint64_t execution_fields[] = {91, 77, 0, 0x030c0ff0, 1, 0};
    unsigned char edges[8] = {0};
    CHECK(otelc_py_journal_origin(6, argv[2], edges, sizeof(edges), execution_fields, 6) == 0);
    if (sdk) {
        CHECK(otelc_py_journal_code(argv[2], code, code_size, 1, 0, 0x030c0ff0, 2) == 0);
        uint64_t join_fields[] = {1, 91, 0, 0, 0, 0};
        CHECK(otelc_py_journal_origin(7, argv[2], NULL, 0, join_fields, 6) == 0);
    }
    otelc_py_journal_finish(1, !loader);
    free(source);
    free(root);
    free(code);
    return 0;
}
