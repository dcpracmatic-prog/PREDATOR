/* COMMONWEAVE Zero — second component: integer statistics + histogram.
 * Deliberately different signatures from matmul: int32/uint32 buffers, a struct out-parameter,
 * a cross-parameter precondition (hi > lo). */
#include <stddef.h>
#include <stdint.h>
#include "stats.h"

int array_stats(const int32_t *data, size_t len, cw_stats *out)
{
    if (!data || !out) return CW_ERR_NULL;
    if (len == 0) return CW_ERR_DIM;
    if (len > 1000000) return CW_ERR_OVERFLOW;
    if (((uintptr_t)data & 3u) || ((uintptr_t)out & 7u)) return CW_ERR_ALIGN;

    int64_t sum = 0;
    int32_t mn = data[0], mx = data[0];
    for (size_t i = 0; i < len; ++i) {
        sum += data[i];
        if (data[i] < mn) mn = data[i];
        if (data[i] > mx) mx = data[i];
    }
    double mean = (double)sum / (double)len;
    double acc = 0.0;
    for (size_t i = 0; i < len; ++i) {
        double d = (double)data[i] - mean;
        acc += d * d;
    }
    out->count = len;
    out->mean = mean;
    out->variance = acc / (double)len;   /* population variance */
    out->min = mn;
    out->max = mx;
    return CW_OK;
}

/* Values outside [lo, hi) are ignored. bins are fully overwritten on success. */
int histogram(const int32_t *data, size_t len, int32_t lo, int32_t hi,
              uint32_t *bins, size_t nbins)
{
    if (!data || !bins) return CW_ERR_NULL;
    if (len == 0 || nbins == 0 || hi <= lo) return CW_ERR_DIM;
    if (len > 1000000 || nbins > 4096) return CW_ERR_OVERFLOW;
    if (((uintptr_t)data & 3u) || ((uintptr_t)bins & 3u)) return CW_ERR_ALIGN;

    for (size_t b = 0; b < nbins; ++b) bins[b] = 0;
    int64_t width = (int64_t)hi - (int64_t)lo;
    for (size_t i = 0; i < len; ++i) {
        int32_t v = data[i];
        if (v < lo || v >= hi) continue;
        size_t b = (size_t)(((int64_t)v - (int64_t)lo) * (int64_t)nbins / width);
        bins[b] += 1;
    }
    return CW_OK;
}
