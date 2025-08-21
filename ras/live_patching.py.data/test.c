#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdbool.h>
#include <string.h>

#define NUM_ATTEMPTS 100
#define LEN 32

static const char *const lp_string = "glibc-livepatch";

int main(int argc, char *argv[])
{
  for (int i = 0; i < NUM_ATTEMPTS; i++) {
    bool flag = false;
    char *m = malloc(LEN);
    m[LEN-1] = '\0';

    fprintf(stderr, "%s\n", m);

    if (m) {
      if (!strcmp(m, lp_string)) {
        flag = true;
      }
      free(m);
    }

    m = calloc(1, 32);
    if (m) {
      free(m);
    } else if (flag) {
      return 0;
    }
    sleep(1);
  }

  return 1;
}
