// Test-only native worker: no Essentia, no audio, no ONNX.
// Reproduces the EFW1/REQ1/RES1 binary protocol for Rust integration tests.
#include <cstdint>
#include <chrono>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
#include <thread>
#include <cstring>
#include <iostream>
#include <string>
#ifdef ESSENTIA_PE_FIXTURE_DEP
extern "C" __declspec(dllimport) int bliss_fixture_dependency();
#endif

static bool read_u32(std::uint32_t& x) {
    char b[4];
    if (!std::cin.read(b, 4)) return false;
    x = 0;
    for (int i = 0; i != 4; ++i)
        x |= std::uint32_t(static_cast<unsigned char>(b[i])) << (i * 8);
    return true;
}
static void write_u32(std::uint32_t x) {
    for (int i = 0; i != 4; ++i) std::cout.put(char(x >> (i * 8)));
}
static void write_u64(std::uint64_t x) {
    for (int i = 0; i != 8; ++i) std::cout.put(char(x >> (i * 8)));
}
static void header(std::uint8_t status, std::uint32_t count) {
    std::cout.write("RES1", 4);
    std::cout.put(char(status));
    write_u32(count);
    write_u64(1000000);
    write_u64(2000000);
}
int main() {
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
        _setmode(_fileno(stdout), _O_BINARY) == -1) return 12;
#endif
#ifdef ESSENTIA_PE_FIXTURE_DEP
    // Fail the handshake if the packaged native import DLL was not actually
    // linked and executed. The mock worker is NEVER an Essentia binary.
    if (bliss_fixture_dependency() != 0x1234) return 11;
#endif
    std::cout.write("EFW1", 4);
    std::cout.flush();
    while (true) {
        char magic[4];
        std::cin.read(magic, 4);
        if (std::cin.gcount() == 0 && std::cin.eof()) return 0;
        if (!std::cin || std::memcmp(magic, "REQ1", 4)) return 2;
        std::uint32_t len = 0, cap = 0;
        if (!read_u32(len) || !read_u32(cap) || len == 0 || len > 16384 || cap > 2048)
            return 3;
        std::string path(len, '\0');
        if (!std::cin.read(path.data(), len)) return 4;
        if (path.find("fail") != std::string::npos) {
            const std::string message = "test worker failure";
            header(1, std::uint32_t(message.size()));
            std::cout.write(message.data(), message.size());
        } else if (path.find("hang") != std::string::npos) {
            std::this_thread::sleep_for(std::chrono::seconds(5));
            continue;
        } else if (path.find("crash") != std::string::npos) {
            return 9;
        } else {
            header(0, 1);
            for (int i = 0; i != 128 * 96; ++i) {
                float f = 0.25f;
                std::uint32_t bits;
                std::memcpy(&bits, &f, sizeof(f));
                if (path.find("binary-bytes") != std::string::npos) {
                    // Little-endian includes CR, LF and CTRL-Z: reject text
                    // mode translations on Windows native pipes.
                    bits = 0x3f1a0a0d;
                }
                write_u32(bits);
            }
        }
        std::cout.flush();
    }
}
