cmake_minimum_required(VERSION 3.20)
project(zkstego_edge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(zkstego_live STATIC src/live.cpp)
target_include_directories(zkstego_live PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_features(zkstego_live PUBLIC cxx_std_20)

add_executable(zkstego_annexb_relay src/relay.cpp)
target_link_libraries(zkstego_annexb_relay PRIVATE zkstego_live)

add_executable(zkstego_live_tests tests/relay_tests.cpp)
target_link_libraries(zkstego_live_tests PRIVATE zkstego_live)

include(CTest)
if(BUILD_TESTING)
  add_test(NAME zkstego_live_tests COMMAND zkstego_live_tests)
endif()
