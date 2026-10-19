/*
 * COMMONWEAVE Zero — native matrix multiplication component
 * Simple double-precision dense matmul with explicit contract-friendly interface.
 * No external dependencies; pure C99.
 */

#include <stddef.h>
#include <string.h>
#include <math.h>

/* Error codes matching the declarative contract */
#define CW_OK            0
#define CW_ERR_NULL      1
#define CW_ERR_DIM       2
#define CW_ERR_OVERFLOW  3
#define CW_ERR_ALIGN     4

/*
 * matmul: C = A * B
 * A is m x k, B is k x n, C is m x n (row-major, contiguous).
 * Returns CW_OK on success or an error code.
 * Does not allocate; caller owns all buffers.
 */
int matmul(const double *A, const double *B, double *C,
           size_t m, size_t k, size_t n)
{
    if (!A || !B || !C)
        return CW_ERR_NULL;
    if (m == 0 || k == 0 || n == 0)
        return CW_ERR_DIM;
    /* Simple overflow guard on total elements */
    if (m > 10000 || k > 10000 || n > 10000)
        return CW_ERR_OVERFLOW;

    for (size_t i = 0; i < m; ++i) {
        for (size_t j = 0; j < n; ++j) {
            double sum = 0.0;
            for (size_t p = 0; p < k; ++p) {
                sum += A[i * k + p] * B[p * n + j];
            }
            C[i * n + j] = sum;
        }
    }
    return CW_OK;
}

/* Buffer processing example: scale + clamp (for secondary validation path) */
int scale_clamp(const double *in, double *out, size_t len,
                double scale, double lo, double hi)
{
    if (!in || !out)
        return CW_ERR_NULL;
    if (len == 0)
        return CW_ERR_DIM;
    for (size_t i = 0; i < len; ++i) {
        double v = in[i] * scale;
        if (v < lo) v = lo;
        if (v > hi) v = hi;
        out[i] = v;
    }
    return CW_OK;
}
