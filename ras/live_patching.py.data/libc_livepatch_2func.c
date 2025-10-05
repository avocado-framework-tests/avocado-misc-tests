#include <stdlib.h>
#include <string.h>

#define MIN(x, y) ((x) < (y) ? (x) : (y))

static const char *const lp_string = "glibc-livepatch";
static const char *const lp_string_realloc = "glibc-livepatch-realloc";

void *malloc_lp(size_t s) {
    char *block = calloc(1, s);
    if (block && s > 0) {
        int lp_string_len = strlen(lp_string);
        int copy_len = MIN(lp_string_len + 1, s);
        memcpy(block, lp_string, copy_len);
        block[s - 1] = '\0';
    }
    return block;
}

void *realloc_lp(void *ptr, size_t new_size) {
        char *new_block = (char *) malloc(2*new_size);
        if (new_block) {
            int lp_string_realloc_len = strlen(lp_string_realloc);
            int copy_len = MIN(lp_string_realloc_len + 1, new_size);
            memcpy(new_block, lp_string_realloc, copy_len);
            new_block[new_size - 1] = '\0';
        }
    return new_block;
}
