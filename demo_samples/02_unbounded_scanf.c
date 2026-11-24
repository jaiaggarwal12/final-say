#include <stdio.h>

/* Demo flaw: %s reads an arbitrary-length token into an 8-byte array. */
int read_name(void) {
    char name[8];
    if (scanf("%s", name) != 1) { /* CWE-120: no field width limit */
        return -1;
    }
    return (unsigned char)name[0];
}
