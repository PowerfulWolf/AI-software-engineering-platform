cmake_minimum_required(VERSION 3.16)
project(ase_cpp_fixture LANGUAGES CXX)

add_executable(hello src/hello.cpp)
target_compile_features(hello PRIVATE cxx_std_17)
