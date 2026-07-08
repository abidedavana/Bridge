#include <hip/hip_runtime.h>

__global__ void saxpy(int n, float a, const float* x, float* y) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) y[i] = a * x[i] + y[i];
}

void run_saxpy(int n, float a, const float* x, float* y) {
  dim3 grid((n + 255) / 256), block(256);
  saxpy<<<grid, block>>>(n, a, x, y);   // triple-chevron; use hipLaunchKernelGGL
}
