# Kompartment's engine in C++.
#
#   cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
#   ctest --test-dir build --output-on-failure
#
# The arithmetic is the other engines' operation for operation: nothing is
# contracted into fused multiply-adds unless the code asks for one
# (-ffp-contract=off), and no flag lets the compiler reorder a sum.

cmake_minimum_required(VERSION 3.20)
project(kompartment_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(KOMPARTMENT_NATIVE "Compile for this machine's processor (-march=native / -mcpu=native)" ON)
option(KOMPARTMENT_SANITIZE "Build with the address and undefined-behaviour sanitizers" OFF)

file(GLOB_RECURSE KOMPARTMENT_SOURCES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp)
list(FILTER KOMPARTMENT_SOURCES EXCLUDE REGEX "/src/main\\.cpp$")
set(KOMPARTMENT_EXCLUDE "" CACHE STRING "A regular expression: the sources and tests whose paths match are left out")
if(KOMPARTMENT_EXCLUDE)
  list(FILTER KOMPARTMENT_SOURCES EXCLUDE REGEX "${KOMPARTMENT_EXCLUDE}")
endif()

add_library(kompartment_core STATIC ${KOMPARTMENT_SOURCES})
target_include_directories(kompartment_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(MSVC)
  target_compile_options(kompartment_core PUBLIC /fp:precise /W3 /utf-8)
else()
  target_compile_options(kompartment_core PUBLIC -ffp-contract=off -fno-fast-math -Wall -Wextra -Wno-unused-parameter)
  if(KOMPARTMENT_NATIVE)
    include(CheckCXXCompilerFlag)
    check_cxx_compiler_flag(-mcpu=native KOMPARTMENT_HAS_MCPU_NATIVE)
    check_cxx_compiler_flag(-march=native KOMPARTMENT_HAS_MARCH_NATIVE)
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64" AND KOMPARTMENT_HAS_MCPU_NATIVE)
      target_compile_options(kompartment_core PUBLIC -mcpu=native)
    elseif(KOMPARTMENT_HAS_MARCH_NATIVE)
      target_compile_options(kompartment_core PUBLIC -march=native)
    endif()
  endif()
  if(KOMPARTMENT_SANITIZE)
    target_compile_options(kompartment_core PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(kompartment_core PUBLIC -fsanitize=address,undefined)
  endif()
endif()

find_package(Threads REQUIRED)
target_link_libraries(kompartment_core PUBLIC Threads::Threads)
find_package(ZLIB)
if(ZLIB_FOUND)
  target_link_libraries(kompartment_core PUBLIC ZLIB::ZLIB)
  target_compile_definitions(kompartment_core PUBLIC KOMPARTMENT_HAVE_ZLIB=1)
endif()

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/src/main.cpp)
  add_executable(kompartment-cpp src/main.cpp)
  target_link_libraries(kompartment-cpp PRIVATE kompartment_core)
endif()

enable_testing()
file(GLOB KOMPARTMENT_TESTS CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_*.cpp)
if(KOMPARTMENT_EXCLUDE)
  list(FILTER KOMPARTMENT_TESTS EXCLUDE REGEX "${KOMPARTMENT_EXCLUDE}")
endif()
foreach(test_source ${KOMPARTMENT_TESTS})
  get_filename_component(test_name ${test_source} NAME_WE)
  add_executable(${test_name} ${test_source})
  target_link_libraries(${test_name} PRIVATE kompartment_core)
  target_include_directories(${test_name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
  target_compile_definitions(${test_name} PRIVATE
    KOMPARTMENT_REPO="${CMAKE_CURRENT_SOURCE_DIR}/.."
    KOMPARTMENT_CPP_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
  add_test(NAME ${test_name} COMMAND ${test_name})
endforeach()
