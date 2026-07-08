#include <cstdio>
__global__ void saxpy(int n, float a, const float* x, float* y){
  int i = blockIdx.x*blockDim.x + threadIdx.x;
  if (i < n) y[i] = a*x[i] + y[i];
}
int main(){
  int n=1<<20; size_t sz=n*sizeof(float);
  float *dx,*dy; cudaMalloc(&dx,sz); cudaMalloc(&dy,sz);
  float *hx=(float*)malloc(sz), *hy=(float*)malloc(sz);
  for(int i=0;i<n;i++){hx[i]=1.f;hy[i]=2.f;}
  cudaMemcpy(dx,hx,sz,cudaMemcpyHostToDevice);
  cudaMemcpy(dy,hy,sz,cudaMemcpyHostToDevice);
  saxpy<<<(n+255)/256,256>>>(n,3.f,dx,dy);
  cudaMemcpy(hy,dy,sz,cudaMemcpyDeviceToHost);
  int bad=0; for(int i=0;i<n;i++) if(hy[i]!=5.f) bad++;
  printf("%s (%d)\n", bad?"FAIL":"PASS", bad); return bad?1:0;
}
