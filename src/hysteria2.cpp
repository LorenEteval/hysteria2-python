#include <string>
#if defined(__MINGW32__) && defined(_M_ARM64)
    // CPython 3.14t uses MSVC's __getReg(18) intrinsic to read the Windows
    // ARM64 thread environment block, but LLVM-MinGW does not provide it.
    // Windows reserves x18 for that pointer, so provide the equivalent here.
    #include <cstdint>
    static inline std::uintptr_t getArm64ThreadPointer()
    {
        std::uintptr_t value;
        __asm__ __volatile__("mov %0, x18" : "=r"(value));
        return value;
    }
    #define __getReg(registerNumber) getArm64ThreadPointer()
#endif
#if defined _WIN64
    #define _hypot hypot
    #include <cmath>
#endif
#include <pybind11/pybind11.h>
#if defined(__MINGW32__) && defined(_M_ARM64)
    #undef __getReg
#endif

#include "hysteria2.h"

namespace py = pybind11;

namespace {
    void startFromJSON(const std::string& json)
    {
        GoString jsonString{json.data(), static_cast<ptrdiff_t>(json.size())};

        {
            py::gil_scoped_release release;

            startClientFromJSON(jsonString);

            py::gil_scoped_acquire acquire;
        }
    }

    // TODO: Audit the C++ and Go code for free-threading safety before using
    // py::mod_gil_not_used() here.
    PYBIND11_MODULE(hysteria2, m) {
        m.def("startFromJSON",
            &startFromJSON,
            "Start Hysteria2 client with JSON",
            py::arg("json"));

        m.attr("__version__") = "2.12.1.1";
    }
}
