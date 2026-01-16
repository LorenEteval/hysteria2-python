#include <string>
#if defined _WIN64
    #define _hypot hypot
    #include <cmath>
#endif
#include <pybind11/pybind11.h>

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

    PYBIND11_MODULE(hysteria2, m) {
        m.def("startFromJSON",
            &startFromJSON,
            "Start Hysteria2 client with JSON",
            py::arg("json"));

        m.attr("__version__") = "2.7.0";
    }
}
