cmake_minimum_required(VERSION 3.15)
project(hysteria2 C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 3 CONFIG REQUIRED)

if (NOT DEFINED HYSTERIA2_GO_BUILD_DIR)
    set(HYSTERIA2_GO_BUILD_DIR "${CMAKE_SOURCE_DIR}/gobuild")
endif ()

if (NOT DEFINED CMAKE_LIBRARY_OUTPUT_DIRECTORY)
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_SOURCE_DIR}/build/lib/${PROJECT_NAME}")
endif ()

pybind11_add_module(${PROJECT_NAME} src/hysteria2.cpp)

if (NOT DEFINED HYSTERIA2_VERSION)
    message(FATAL_ERROR "HYSTERIA2_VERSION must be provided by the package build")
endif ()
target_compile_definitions(
    ${PROJECT_NAME} PRIVATE HYSTERIA2_VERSION="${HYSTERIA2_VERSION}"
)

if (WIN32)
    if (MINGW)
        target_compile_options(${PROJECT_NAME} PRIVATE "-Wa,-mbig-obj")
        target_link_options(
            ${PROJECT_NAME} PRIVATE
            "-static-libgcc" "-static-libstdc++"
            "-Wl,-Bstatic,--whole-archive"
            "-lwinpthread"
            "-Wl,--no-whole-archive"
        )
    endif ()

    target_link_libraries(
        ${PROJECT_NAME} PRIVATE
        "${HYSTERIA2_GO_BUILD_DIR}/hysteria2.lib"
    )
else ()
    target_link_libraries(
        ${PROJECT_NAME} PRIVATE
        "${HYSTERIA2_GO_BUILD_DIR}/hysteria2.a"
        "-lresolv"
    )

    if (APPLE)
        target_link_libraries(
            ${PROJECT_NAME} PRIVATE
            "-framework CoreFoundation"
            "-framework Security"
        )
    endif ()
endif ()

target_include_directories(${PROJECT_NAME} PRIVATE "${HYSTERIA2_GO_BUILD_DIR}")
