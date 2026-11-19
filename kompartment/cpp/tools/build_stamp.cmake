# Writes the engine's build stamp (KOMPARTMENT_BUILD_STAMP in a header of its own): a hash
# of every source of the engine and of how it was compiled. What auto learns about
# splitting a model (src/engine/split.cpp) is kept by it, so that what one build measured
# is not taken to hold for another -- as the Julia package keeps it by a hash of its code.
#
#   cmake -DSOURCE_DIR=<the engine's folder> -DOUT=<header> -DHOW=<compiler and flags> -P build_stamp.cmake
#
# The header is written only when the stamp changes, so that what includes it is compiled
# again only then.

file(GLOB_RECURSE sources RELATIVE "${SOURCE_DIR}" "${SOURCE_DIR}/src/*.cpp" "${SOURCE_DIR}/src/*.hpp")
list(SORT sources)
set(text "${HOW}\n")
foreach(f IN LISTS sources)
  file(SHA256 "${SOURCE_DIR}/${f}" h)
  string(APPEND text "${f} ${h}\n")
endforeach()
string(SHA256 stamp "${text}")
string(SUBSTRING "${stamp}" 0 16 stamp)
set(content "// Written by tools/build_stamp.cmake: a hash of the engine's sources and of how they were compiled.\n#pragma once\n#define KOMPARTMENT_BUILD_STAMP \"${stamp}\"\n")
set(old "")
if(EXISTS "${OUT}")
  file(READ "${OUT}" old)
endif()
if(NOT old STREQUAL content)
  file(WRITE "${OUT}" "${content}")
endif()
