#include <string.h>

/* Demo flaw: input length is not checked against the 16-byte destination. */
int copy_name(const char *input) {
    char name[16];
    strcpy(name, input); /* CWE-120: possible stack buffer overflow */
    return (unsigned char)name[0];
}
