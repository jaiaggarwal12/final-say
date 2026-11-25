#include <stdio.h>

/* Demo flaw: gets has no way to learn the destination capacity. */
int read_label(void) {
    char label[16];
    if (gets(label) == NULL) { /* CWE-242: inherently dangerous function */
        return -1;
    }
    return (unsigned char)label[0];
}
