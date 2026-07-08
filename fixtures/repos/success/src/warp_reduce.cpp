#include <hip/hip_runtime.h>

// Warp-level reduction that assumes a 32-lane warp. On CDNA (MI300X) warpSize is
// 64, so both the loop start (16 = 32/2) and the 32-bit shuffle mask are wrong.
__global__ void warp_reduce(const float* in, float* out, int n) {
  float v = (threadIdx.x < n) ? in[threadIdx.x] : 0.0f;
  for (int offset = 16; offset > 0; offset >>= 1)        // assumes warpSize == 32
    v += __shfl_down_sync(0xffffffff, v, offset);        // 32-bit mask on a 64-lane warp
  if (threadIdx.x == 0) out[blockIdx.x] = v;
}
