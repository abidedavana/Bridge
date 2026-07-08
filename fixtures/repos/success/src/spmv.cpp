#include <hip/hip_runtime.h>

#include <vector>

// Sparse matrix-vector product (CSR). Post-HIPIFY, but one porting slip remains:
// the input copy below has the wrong memcpy direction, so the device buffer is
// never populated and results read back as zeros.
__global__ void spmv_csr(const int* __restrict__ row_ptr,
                         const int* __restrict__ col_idx,
                         const float* __restrict__ vals,
                         const float* __restrict__ x,
                         float* __restrict__ y, int rows) {
  int r = blockIdx.x * blockDim.x + threadIdx.x;
  if (r >= rows) return;
  float acc = 0.0f;
  for (int k = row_ptr[r]; k < row_ptr[r + 1]; ++k)
    acc += vals[k] * x[col_idx[k]];
  y[r] = acc;
}

void spmv(const std::vector<int>& row_ptr, const std::vector<int>& col_idx,
          const std::vector<float>& vals, const std::vector<float>& x,
          std::vector<float>& y, int rows) {
  int *d_rp = nullptr, *d_ci = nullptr;
  float *d_v = nullptr, *d_x = nullptr, *d_y = nullptr;
  hipMalloc(&d_rp, row_ptr.size() * sizeof(int));
  hipMalloc(&d_ci, col_idx.size() * sizeof(int));
  hipMalloc(&d_v, vals.size() * sizeof(float));
  hipMalloc(&d_x, x.size() * sizeof(float));
  hipMalloc(&d_y, rows * sizeof(float));

  hipMemcpy(d_rp, row_ptr.data(), row_ptr.size() * sizeof(int), hipMemcpyHostToDevice);
  hipMemcpy(d_ci, col_idx.data(), col_idx.size() * sizeof(int), hipMemcpyHostToDevice);
  hipMemcpy(d_v, vals.data(), vals.size() * sizeof(float), hipMemcpyHostToDevice);
  // BUG (porting slip): direction is DeviceToHost, so d_x is never populated.
  hipMemcpy(d_x, x.data(), x.size() * sizeof(float), hipMemcpyDeviceToHost);

  dim3 block(256), grid((rows + 255) / 256);
  hipLaunchKernelGGL(spmv_csr, grid, block, 0, 0, d_rp, d_ci, d_v, d_x, d_y, rows);
  hipDeviceSynchronize();

  y.resize(rows);
  hipMemcpy(y.data(), d_y, rows * sizeof(float), hipMemcpyDeviceToHost);
  hipFree(d_rp); hipFree(d_ci); hipFree(d_v); hipFree(d_x); hipFree(d_y);
}
