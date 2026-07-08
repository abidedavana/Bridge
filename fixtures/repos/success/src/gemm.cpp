#include "gemm.hpp"
#include <hip/hip_runtime.h>

// cuBLAS calls HIPIFY left unmapped; hipBLAS mirrors the cuBLAS-v2 API.
void gemm(int n) {
  cublasHandle_t handle;                 // -> hipblasHandle_t
  cublasCreate(&handle);                 // -> hipblasCreate
  float alpha = 1.0f, beta = 0.0f;
  cublasSgemm(handle, HIPBLAS_OP_N, HIPBLAS_OP_N, n, n, n,
              &alpha, nullptr, n, nullptr, n, &beta, nullptr, n);  // -> hipblasSgemm
  cublasDestroy(handle);                 // -> hipblasDestroy
}
