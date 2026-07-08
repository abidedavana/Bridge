cmake_minimum_required(VERSION 3.18)
project(bridge_demo LANGUAGES CXX)

# --- to port: CUDA language + toolkit -> HIP -------------------------------
enable_language(CUDA)                 # replace with: enable_language(HIP)
find_package(CUDAToolkit REQUIRED)    # replace with: find_package(hip REQUIRED)

set(CMAKE_CUDA_ARCHITECTURES 70)
add_compile_options(-arch=sm_70)      # nvcc flag; use --offload-arch=gfx942

add_executable(gemm src/gemm.cpp)
add_executable(saxpy src/saxpy.cpp)
add_executable(warp_reduce src/warp_reduce.cpp)
add_executable(spmv src/spmv.cpp)

target_link_libraries(gemm CUDA::cublas)   # replace with: roc::hipblas
