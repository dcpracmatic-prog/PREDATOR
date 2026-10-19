#ifndef STATS_H
#define STATS_H
#include <stddef.h>
#include <stdint.h>
#define CW_OK            0
#define CW_ERR_NULL      1
#define CW_ERR_DIM       2
#define CW_ERR_OVERFLOW  3
#define CW_ERR_ALIGN     4

typedef struct { size_t count; double mean; double variance; int32_t min; int32_t max; } cw_stats;

int array_stats(const int32_t *data, size_t len, cw_stats *out);
int histogram(const int32_t *data, size_t len, int32_t lo, int32_t hi, uint32_t *bins, size_t nbins);
#endif
