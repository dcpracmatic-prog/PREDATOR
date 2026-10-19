#ifndef MATMUL_H
#define MATMUL_H

#include <stddef.h>

#define CW_OK            0
#define CW_ERR_NULL      1
#define CW_ERR_DIM       2
#define CW_ERR_OVERFLOW  3
#define CW_ERR_ALIGN     4

int matmul(const double *A, const double *B, double *C,
           size_t m, size_t k, size_t n);

int scale_clamp(const double *in, double *out, size_t len,
                double scale, double lo, double hi);

#endif
