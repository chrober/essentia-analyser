// Test-only C++ shared library for checking real PE import closure.
// This is NOT Essentia and must never be included in production worker bundles.
#ifdef _WIN32
extern "C" __declspec(dllexport) int bliss_fixture_dependency() {
    return 0x1234;
}
#else
extern "C" int bliss_fixture_dependency() {
    return 0x1234;
}
#endif
