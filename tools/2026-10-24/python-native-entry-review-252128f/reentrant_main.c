/* Read-only review fixture: a genuine nested public Py_RunMain call. */
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int entered;
static int hook(const char *event, PyObject *args, void *unused) {
    (void)unused;
    const char *path = getenv("REVIEW_ENTRY"), *report = getenv("REVIEW_REPORT");
    if (entered || !path || !report || strcmp(event, "compile") || PyEval_GetFrame()
            || !PyTuple_CheckExact(args) || PyTuple_GET_SIZE(args) != 2) return 0;
    PyObject *name = PyTuple_GET_ITEM(args, 1), *expected = PyUnicode_DecodeFSDefault(path);
    int same = expected && PyUnicode_CheckExact(name) && !PyUnicode_Compare(name, expected);
    Py_XDECREF(expected);
    if (!same) return 0;
    entered = 1;
    FILE *input = fopen(path, "rb");
    if (!input || fseek(input, 0, SEEK_END)) exit(81);
    long size = ftell(input);
    if (size < 0 || size > 65536 || fseek(input, 0, SEEK_SET)) exit(82);
    char *original = malloc((size_t)size + 1);
    if (!original || fread(original, 1, (size_t)size, input) != (size_t)size) exit(83);
    fclose(input);
    const char *foreign = "spoofed_native_compiler_root=123\ndef chosen(value): return value*2+3\nprint(chosen(7))\n";
    FILE *output = fopen(path, "wb");
    if (!output || fwrite(foreign, 1, strlen(foreign), output) != strlen(foreign) || fclose(output)) exit(84);
    int status = Py_RunMain();
    output = fopen(path, "wb");
    if (!output || fwrite(original, 1, (size_t)size, output) != (size_t)size || fclose(output)) exit(85);
    free(original);
    output = fopen(report, "w");
    if (!output) exit(86);
    fprintf(output, "{\"nested_main_returned\":true,\"status\":%d,\"original_restored\":true}\n", status);
    fclose(output);
    exit(status);
}
__attribute__((constructor)) static void install(void) {
    if (PySys_AddAuditHook(hook, NULL)) exit(87);
}
