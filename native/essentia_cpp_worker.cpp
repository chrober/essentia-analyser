// Persistent, strictly single-threaded Essentia C++ DSP child.
// Compile against the original MTG/essentia library (no essentia-rs).
// All stdout bytes implement EFW1/REQ1/RES1; diagnostic text goes to stderr.
#include <essentia.h>
#include <algorithmfactory.h>
#include <algorithm.h>
#include <types.h>

#include <algorithm>
#include <cstring>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {
constexpr std::uint32_t kMaxPath = 16384;
constexpr std::uint32_t kMaxPatches = 2048;
constexpr std::size_t kFrame = 512;
constexpr std::size_t kHop = 256;
constexpr std::size_t kBands = 96;
constexpr std::size_t kPatchFrames = 128;
constexpr std::size_t kPatchHop = 62;
constexpr std::size_t kMaxError = 4096;
using Clock = std::chrono::steady_clock;

void write_u32(std::uint32_t value) {
    for (unsigned n = 0; n != 4; ++n) std::cout.put(char(value >> (8 * n)));
}
void write_u64(std::uint64_t value) {
    for (unsigned n = 0; n != 8; ++n) std::cout.put(char(value >> (8 * n)));
}
std::uint32_t read_u32() {
    char bytes[4];
    if (!std::cin.read(bytes, 4)) throw std::runtime_error("truncated request integer");
    std::uint32_t value = 0;
    for (unsigned n = 0; n != 4; ++n)
        value |= std::uint32_t(static_cast<unsigned char>(bytes[n])) << (8 * n);
    return value;
}
void write_f32(float value) {
    static_assert(sizeof(float) == 4, "IEEE-754 binary32 is required");
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    write_u32(bits);
}
std::uint64_t elapsed_ns(Clock::time_point since) {
    return std::uint64_t(std::chrono::duration_cast<
        std::chrono::nanoseconds>(Clock::now() - since).count());
}
void header(unsigned char status, std::uint32_t count,
            std::uint64_t decode_ns, std::uint64_t features_ns) {
    std::cout.write("RES1", 4);
    std::cout.put(char(status));
    write_u32(count);
    write_u64(decode_ns);
    write_u64(features_ns);
}
void error_reply(std::string message) {
    if (message.size() > kMaxError) message.resize(kMaxError);
    header(1, std::uint32_t(message.size()), 0, 0);
    std::cout.write(message.data(), std::streamsize(message.size()));
    std::cout.flush();
}
struct Patches {
    std::vector<std::vector<essentia::Real>> bands;
    std::size_t count;
    std::uint64_t decode_ns;
    std::uint64_t features_ns;
};

Patches analyze(const std::string& path, std::uint32_t limit) {
    using essentia::Real;
    using essentia::standard::Algorithm;
    const auto started = Clock::now();
    auto& factory = essentia::standard::AlgorithmFactory::instance();

    std::unique_ptr<Algorithm> loader(factory.create(
        "MonoLoader", "filename", path, "sampleRate", Real(16000),
        "downmix", "mix", "resampleQuality", 4));
    std::vector<Real> audio;
    loader->output("audio").set(audio);
    loader->compute();
    const auto decode_ns = elapsed_ns(started);
    if (audio.empty()) throw std::runtime_error("empty decoded audio");
    if (audio.size() < kFrame) throw std::runtime_error("audio too short");

    // The original Essentia FrameCutter controls centered zero-padding.
    std::unique_ptr<Algorithm> cutter(factory.create(
        "FrameCutter", "frameSize", int(kFrame), "hopSize", int(kHop),
        "startFromZero", false, "validFrameThresholdRatio", Real(0)));
    std::unique_ptr<Algorithm> tim(factory.create("TensorflowInputMusiCNN"));
    std::vector<Real> frame, bands;
    cutter->input("signal").set(audio);
    cutter->output("frame").set(frame);
    tim->input("frame").set(frame);
    tim->output("bands").set(bands);

    Patches result;
    result.decode_ns = decode_ns;
    result.features_ns = 0;
    // No extra FFT/filter bank code: this is the original Essentia pipeline.
    // Reference TensorflowPredictEffnetDiscogs uses ceil(samples / hop)
    // frames. Stand-alone FrameCutter may return one additional final frame.
    const auto expected_frames = (audio.size() + kHop - 1) / kHop;
    while (result.bands.size() < expected_frames) {
        cutter->compute();
        if (frame.empty()) break;
        tim->compute();
        if (bands.size() != kBands) throw std::runtime_error("unexpected Essentia mel bands");
        for (Real v : bands) {
            if (!std::isfinite(v) || v < 0) throw std::runtime_error("invalid mel coefficient");
        }
        result.bands.push_back(bands);
    }
    const auto frames = result.bands.size();
    if (frames < kPatchFrames) throw std::runtime_error("audio too short for EffNet patch");
    const auto available = 1 + (frames - kPatchFrames) / kPatchHop;
    // A missing user patch cap is NOT permission to silently truncate a song.
    if (available > kMaxPatches && limit == 0)
        throw std::runtime_error("song exceeds native IPC patch cap; specify a smaller explicit max-patches");
    result.count = limit == 0 ? available : std::min<std::size_t>(available, limit);
    if (result.count == 0 || result.count > kMaxPatches)
        throw std::runtime_error("invalid native patch count");
    result.features_ns = elapsed_ns(started) - decode_ns;
    return result;
}
void success_reply(const Patches& p) {
    header(0, std::uint32_t(p.count), p.decode_ns, p.features_ns);
    for (std::size_t n = 0; n < p.count; ++n) {
        const auto begin = n * kPatchHop;
        for (std::size_t i = 0; i < kPatchFrames; ++i) {
            for (auto value : p.bands[begin + i]) write_f32(float(value));
        }
    }
    std::cout.flush();
}
void run() {
    while (true) {
        char magic[4];
        std::cin.read(magic, 4);
        if (std::cin.gcount() == 0 && std::cin.eof()) break;
        if (!std::cin || std::string(magic, 4) != "REQ1") {
            throw std::runtime_error("invalid native request magic");
        }
        const auto path_size = read_u32();
        const auto patch_cap = read_u32();
        if (!path_size || path_size > kMaxPath || patch_cap > kMaxPatches) {
            throw std::runtime_error("request outside fixed IPC bounds");
        }
        std::string path(path_size, '\0');
        if (!std::cin.read(&path[0], std::streamsize(path_size)))
            throw std::runtime_error("truncated native path");
        if (path.find('\0') != std::string::npos)
            throw std::runtime_error("invalid NUL in audio path");
        try {
            success_reply(analyze(path, patch_cap));
        } catch (const std::exception& e) {
            error_reply(e.what());
        }
        if (!std::cout) throw std::runtime_error("parent pipe closed");
    }
}
} // namespace

int main() {
    try {
#ifdef _WIN32
        // Windows CRT text mode may convert LF bytes inside binary f32
        // Mel patches to CRLF and reinterpret 0x1A on stdin as EOF.
        // Both pipes MUST be byte-exact before any EFW1/REQ1/RES1 traffic.
        if (_setmode(_fileno(stdin), _O_BINARY) == -1 ||
            _setmode(_fileno(stdout), _O_BINARY) == -1) {
            throw std::runtime_error("failed to set native Essentia IPC pipe binary mode");
        }
#endif
        essentia::init();
        // Handshake only after original Essentia has initialized.
        std::cout.write("EFW1", 4);
        std::cout.flush();
        run();
        essentia::shutdown();
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "essentia-cpp-worker fatal: " << e.what() << "\n";
        return 1;
    }
}
