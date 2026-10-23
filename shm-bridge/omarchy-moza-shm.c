/* Forwards Assetto Corsa Competizione and Le Mans Ultimate shared memory to
 * the MOZA plugin on Linux. Both games publish telemetry only as Windows
 * shared memory, which exists only inside the game's Proton prefix, so Proton
 * starts this helper next to the game (PROTON_REMOTE_DEBUG_CMD) and kills it
 * with the game.
 *
 * It copies a few fixed byte ranges and sends them to 127.0.0.1:9998, about
 * 100 times a second. All parsing happens in Rust (rev/src/shm.rs), where it
 * is tested. It never creates a mapping: a game would silently reuse ours.
 *
 * Datagram: "OMZ1", game (1 ACC, 2 LMU), three zero bytes, then
 *   ACC: graphics[0..8) (packetId, status), static maxRpm (4), physics[0..800)
 *   LMU: appInfo.mOptionsLocation (1), scoring[1736..1748) (12),
 *        telemetry header[128464..128468) (4), player TelemInfoV01 (1888)
 *
 * Copyright Carmine Paolino. GPL-3.0-only.
 */
#include <winsock2.h>
#include <windows.h>
#include <string.h>

#define PORT 9998
#define ACC_PHYSICS 800
#define LMU_SIZE 324824
#define LMU_RECORD 1888
#define LMU_RECORDS 128468
#define LMU_VEHICLES 104

static const void *open_view(const wchar_t *name) {
  HANDLE map = OpenFileMappingW(FILE_MAP_READ, FALSE, name);
  if (!map) return NULL;
  const void *view = MapViewOfFile(map, FILE_MAP_READ, 0, 0, 0);
  CloseHandle(map); /* the view keeps the section alive */
  return view;
}

static size_t view_size(const void *view) {
  MEMORY_BASIC_INFORMATION info;
  return VirtualQuery(view, &info, sizeof info) ? info.RegionSize : 0;
}

static size_t header(unsigned char *out, unsigned char game) {
  memcpy(out, "OMZ1", 4);
  out[4] = game;
  out[5] = out[6] = out[7] = 0;
  return 8;
}

static size_t acc(unsigned char *out, const unsigned char *physics,
                  const unsigned char *graphics, const unsigned char *statics) {
  size_t n = header(out, 1);
  /* No lock exists: accept the copy only if packetId did not move. */
  for (int attempt = 0; attempt < 4; ++attempt) {
    LONG before = *(volatile const LONG *)physics;
    memcpy(out + n, graphics, 8);
    memcpy(out + n + 8, statics + 412, 4);
    memcpy(out + n + 12, physics, ACC_PHYSICS);
    if (*(volatile const LONG *)physics == before) return n + 12 + ACC_PHYSICS;
  }
  return 0;
}

static size_t lmu(unsigned char *out, const unsigned char *data) {
  size_t n = header(out, 2);
  unsigned char active = data[128464], player = data[128465], has = data[128466];
  if (!has || player >= active || player >= LMU_VEHICLES) return 0;
  out[n] = data[96];
  memcpy(out + n + 1, data + 1736, 12);
  memcpy(out + n + 13, data + 128464, 4);
  memcpy(out + n + 17, data + LMU_RECORDS + (size_t)player * LMU_RECORD, LMU_RECORD);
  return n + 17 + LMU_RECORD;
}

int main(void) {
  WSADATA wsa;
  if (WSAStartup(MAKEWORD(2, 2), &wsa)) return 1;
  SOCKET sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (sock == INVALID_SOCKET) return 1;
  struct sockaddr_in to = {0};
  to.sin_family = AF_INET;
  to.sin_port = htons(PORT);
  to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

  const unsigned char *physics = NULL, *graphics = NULL, *statics = NULL, *lmu_data = NULL;
  unsigned char packet[8 + 17 + LMU_RECORD];
  for (DWORD tick = 0;; ++tick) {
    /* The helper usually starts before the game creates its memory. */
    if (tick % 50 == 0) {
      if (!physics) physics = open_view(L"Local\\acpmf_physics");
      if (!graphics) graphics = open_view(L"Local\\acpmf_graphics");
      if (!statics) statics = open_view(L"Local\\acpmf_static");
      if (!lmu_data) {
        lmu_data = open_view(L"LMU_Data");
        if (lmu_data && view_size(lmu_data) < LMU_SIZE) {
          UnmapViewOfFile(lmu_data);
          lmu_data = NULL;
        }
      }
    }
    /* Forward each game found; the plugin ignores frames that stop advancing. */
    size_t n = physics && graphics && statics ? acc(packet, physics, graphics, statics) : 0;
    if (n) sendto(sock, (const char *)packet, (int)n, 0, (struct sockaddr *)&to, sizeof to);
    n = lmu_data ? lmu(packet, lmu_data) : 0;
    if (n) sendto(sock, (const char *)packet, (int)n, 0, (struct sockaddr *)&to, sizeof to);
    Sleep(10);
  }
}
