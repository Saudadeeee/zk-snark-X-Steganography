cmake_minimum_required(VERSION 3.20)
project(zkstego_live LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(zkstego_live STATIC src/live.c src/cavlc_direct.c)
target_include_directories(zkstego_live PUBLIC include)
if(MSVC)
  target_compile_options(zkstego_live PRIVATE /W4 /WX)
else()
  target_compile_options(zkstego_live PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(zkstego_live_tests tests/test_live.c)
target_link_libraries(zkstego_live_tests PRIVATE zkstego_live)

add_executable(zkstego_annexb_relay src/relay.c)
target_link_libraries(zkstego_annexb_relay PRIVATE zkstego_live)

enable_testing()
add_test(NAME zkstego_live_tests COMMAND zkstego_live_tests)

option(ZKS_WITH_X264 "Build the optional patched-x264 direct-CAVLC encoder adapter" OFF)
if(ZKS_WITH_X264)
  find_path(X264_INCLUDE_DIR x264.h)
  find_library(X264_LIBRARY NAMES x264 libx264)
  if(NOT X264_INCLUDE_DIR OR NOT X264_LIBRARY)
    message(FATAL_ERROR "ZKS_WITH_X264=ON requires x264 headers and library")
  endif()
  add_library(zkstego_x264 STATIC src/x264_encoder.c)
  target_include_directories(zkstego_x264 PUBLIC include PRIVATE ${X264_INCLUDE_DIR})
  target_link_libraries(zkstego_x264 PUBLIC ${X264_LIBRARY})

  add_executable(zkstego_x264_smoke x264_fork/tests/zkstego_x264_smoke.c)
  target_include_directories(zkstego_x264_smoke PRIVATE ${X264_INCLUDE_DIR})
  target_link_libraries(zkstego_x264_smoke PRIVATE ${X264_LIBRARY})
  set(ZKS_X264_SMOKE_VIDEO "${CMAKE_CURRENT_BINARY_DIR}/zkstego_x264_smoke.h264")
  add_test(NAME zkstego_x264_smoke
    COMMAND zkstego_x264_smoke "${ZKS_X264_SMOKE_VIDEO}")

  add_executable(zkstego_x264_adapter_smoke x264_fork/tests/zkstego_adapter_smoke.c)
  target_link_libraries(zkstego_x264_adapter_smoke PRIVATE zkstego_x264)
  add_test(NAME zkstego_x264_adapter_smoke COMMAND zkstego_x264_adapter_smoke)

  find_package(Python3 COMPONENTS Interpreter QUIET)
  if(Python3_Interpreter_FOUND)
    add_test(NAME zkstego_blind_extract_smoke
      COMMAND ${Python3_EXECUTABLE}
        "${CMAKE_CURRENT_SOURCE_DIR}/x264_fork/tests/blind_extract_smoke.py"
        "${ZKS_X264_SMOKE_VIDEO}" a5)
    set_tests_properties(zkstego_blind_extract_smoke
      PROPERTIES DEPENDS zkstego_x264_smoke)
  endif()

  if(MSVC)
    target_compile_options(zkstego_x264 PRIVATE /W4 /WX)
    target_compile_options(zkstego_x264_smoke PRIVATE /W4 /WX)
    target_compile_options(zkstego_x264_adapter_smoke PRIVATE /W4 /WX)
  else()
    target_compile_options(zkstego_x264 PRIVATE -Wall -Wextra -Wpedantic -Werror)
    target_compile_options(zkstego_x264_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror)
    target_compile_options(zkstego_x264_adapter_smoke PRIVATE -Wall -Wextra -Wpedantic -Werror)
  endif()
endif()
