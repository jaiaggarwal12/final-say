#include <stdio.h>
#include <stdlib.h>

/* Demo flaw: untrusted filename is interpolated into a shell command. */
int show_file(const char *filename) {
    char command[512];
    (void)snprintf(command, sizeof(command), "cat %s", filename);
    return system(command); /* CWE-78: shell metacharacters can alter the command */
}
