#ifndef OTELEQ_NATIVE_RENDEZVOUS_H
#define OTELEQ_NATIVE_RENDEZVOUS_H
#if defined(__APPLE__) && !defined(_DARWIN_C_SOURCE)
#define _DARWIN_C_SOURCE
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Tool-owned only. Close immutable data before publishing the ready directory.
   A later hard-link unlink would change ctime and race the host's file guard. */
static int __oteleq_native_path(char *path, size_t size, const char *phase, const char *suffix) {
  const char *root = getenv("OTELEQ_NATIVE_CONTROL_ROOT");
  int count;
  if (!root || root[0] != '/') return 0;
  count = snprintf(path, size, "%s/%s.%s", root, phase, suffix);
  return count > 0 && (size_t)count < size;
}

static int __oteleq_native_message(char *out, size_t size, const char *phase) {
  const char *token = getenv("OTELEQ_NATIVE_CONTROL_TOKEN");
  size_t index;
  int count;
  if (!token || strlen(token) != 32 || !phase[0] || strlen(phase) > 24) return 0;
  for (index = 0; index < 32; ++index)
    if (!((token[index] >= '0' && token[index] <= '9') || (token[index] >= 'a' && token[index] <= 'f'))) return 0;
  for (index = 0; phase[index]; ++index)
    if (!((phase[index] >= 'a' && phase[index] <= 'z') || (phase[index] >= '0' && phase[index] <= '9') || phase[index] == '-')) return 0;
  count = snprintf(out, size, "{\"nonce\":\"%s\",\"phase\":\"%s\"}\n", token, phase);
  return count > 0 && (size_t)count < size ? count : 0;
}

static int __oteleq_native_write(int fd, const char *value, size_t size) {
  size_t offset = 0;
  while (offset < size) {
    ssize_t count = write(fd, value + offset, size - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return 0;
    offset += (size_t)count;
  }
  return 1;
}

static int __oteleq_native_checkpoint_impl(const char *phase) {
  char path[4096], expected[256], received[256];
  struct stat info;
  struct timespec delay = {0, 1000000};
  int fd, good, length = __oteleq_native_message(expected, sizeof(expected), phase);
  size_t offset;
  if (!length || !__oteleq_native_path(path, sizeof(path), phase, "ready.json")) return 0;
  fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) return 0;
  good = __oteleq_native_write(fd, expected, (size_t)length);
  if (close(fd) != 0 || !good) return 0;
  if (!__oteleq_native_path(path, sizeof(path), phase, "ready") || mkdir(path, 0700) != 0) return 0;
  if (!__oteleq_native_path(path, sizeof(path), phase, "resume")) return 0;
  for (;;) {
    if (lstat(path, &info) == 0) break;
    if (errno != ENOENT) return 0;
    (void)nanosleep(&delay, NULL);
  }
  if (!S_ISDIR(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 0777) != 0700) return 0;
  if (!__oteleq_native_path(path, sizeof(path), phase, "resume.json")) return 0;
  fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
  if (fd < 0) return 0;
  good = fstat(fd, &info) == 0 && S_ISREG(info.st_mode) && info.st_uid == getuid()
      && (info.st_mode & 0777) == 0600 && info.st_nlink == 1 && info.st_size == length;
  offset = 0;
  while (good && offset < sizeof(received)) {
    ssize_t count = read(fd, received + offset, sizeof(received) - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count < 0) { good = 0; break; }
    if (!count) break;
    offset += (size_t)count;
  }
  if (close(fd) != 0) good = 0;
  return good && offset == (size_t)length && memcmp(received, expected, offset) == 0;
}

static int __oteleq_native_checkpoint(const char *phase) {
  int saved = errno;
  int result = __oteleq_native_checkpoint_impl(phase);
  errno = saved;
  return result;
}

static FILE *__oteleq_native_frame(unsigned int index) {
  char path[4096], phase[32];
  int saved = errno;
  int fd, count = snprintf(phase, sizeof(phase), "step-%u", index);
  FILE *result;
  if (count <= 0 || (size_t)count >= sizeof(phase)
      || !__oteleq_native_path(path, sizeof(path), phase, "observation")) return NULL;
  fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) return NULL;
  result = fdopen(fd, "wb");
  if (!result) close(fd);
  errno = saved;
  return result;
}
#endif
