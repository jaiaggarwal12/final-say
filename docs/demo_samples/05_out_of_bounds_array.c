/* Demo flaw: index 8 is outside the valid indices 0 through 3. */
int lookup_value(void) {
    int values[4] = {10, 20, 30, 40};
    return values[8]; /* CWE-788: out-of-bounds read */
}
