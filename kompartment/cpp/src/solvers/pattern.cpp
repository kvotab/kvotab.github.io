#include "solvers/pattern.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <string>

namespace kompartment {

namespace {

// sqrt(2^-52)
const double JAC_SQRT_EPS = 0x1p-26;

}  // namespace

Pattern::Pattern(int n_, const std::vector<I32>& rows, const std::vector<I32>& cols) : n(n_) {
    if (rows.size() != cols.size()) throw std::invalid_argument("rows and cols differ in length");
    const std::size_t m = rows.size();
    std::vector<I32> count(static_cast<std::size_t>(n) + 1, 0);
    for (std::size_t q = 0; q < m; q++) {
        const I32 c = cols[q];
        const I32 r = rows[q];
        if (!(0 <= c && c < n && 0 <= r && r < n)) {
            throw std::invalid_argument("entry (" + std::to_string(r) + ", " + std::to_string(c) + ") is outside a " +
                                        std::to_string(n) + " by " + std::to_string(n) + " pattern");
        }
        count[c + 1] += 1;
    }
    std::vector<I32> ptr(static_cast<std::size_t>(n) + 1, 0);
    for (int j = 0; j < n; j++) ptr[j + 1] = ptr[j] + count[j + 1];
    std::vector<I32> next(ptr.begin(), ptr.begin() + n);
    std::vector<I32> raw(m);
    for (std::size_t q = 0; q < m; q++) {
        const I32 c = cols[q];
        raw[next[c]] = rows[q];
        next[c] += 1;
    }
    colptr.assign(static_cast<std::size_t>(n) + 1, 0);
    rowval.clear();
    rowval.reserve(m);
    for (int j = 0; j < n; j++) {
        std::sort(raw.begin() + ptr[j], raw.begin() + ptr[j + 1]);
        I32 last = -1;
        for (I32 q = ptr[j]; q < ptr[j + 1]; q++) {
            const I32 r = raw[q];
            if (r != last) {
                rowval.push_back(r);
                last = r;
            }
        }
        colptr[j + 1] = static_cast<I32>(rowval.size());
    }
    col_of.resize(rowval.size());
    for (int j = 0; j < n; j++)
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) col_of[p] = j;
}

ColumnGroups colour_columns(const Pattern& p) {
    const int n = p.n;
    const std::vector<I32>& colptr = p.colptr;
    const std::vector<I32>& rowval = p.rowval;
    // For each row, the columns with an entry in it (the pattern by rows).
    std::vector<I32> rcount(static_cast<std::size_t>(n) + 1, 0);
    for (I32 r : rowval) rcount[r + 1] += 1;
    std::vector<I32> rowptr(static_cast<std::size_t>(n) + 1, 0);
    for (int i = 0; i < n; i++) rowptr[i + 1] = rowptr[i] + rcount[i + 1];
    std::vector<I32> rowcols(rowval.size());
    std::vector<I32> nxt(rowptr.begin(), rowptr.begin() + n);
    for (int j = 0; j < n; j++) {
        for (I32 q = colptr[j]; q < colptr[j + 1]; q++) {
            const I32 r = rowval[q];
            rowcols[nxt[r]] = j;
            nxt[r] += 1;
        }
    }
    std::vector<I32> order(static_cast<std::size_t>(n));
    std::iota(order.begin(), order.end(), 0);
    // Stable, as Array.sort is: the largest degree first, ties in column order.
    std::stable_sort(order.begin(), order.end(), [&](I32 a, I32 b) {
        return colptr[a + 1] - colptr[a] > colptr[b + 1] - colptr[b];
    });
    std::vector<I32> colour(static_cast<std::size_t>(n), -1);
    std::vector<I32> used(static_cast<std::size_t>(n) + 1, -1);
    I32 ncolours = 0;
    for (I32 j : order) {
        for (I32 k = colptr[j]; k < colptr[j + 1]; k++) {
            const I32 r = rowval[k];
            for (I32 q = rowptr[r]; q < rowptr[r + 1]; q++) {
                const I32 c = colour[rowcols[q]];
                if (c >= 0) used[c] = j;
            }
        }
        I32 c = 0;
        while (used[c] == j) c += 1;
        colour[j] = c;
        ncolours = std::max(ncolours, c + 1);
    }
    ColumnGroups groups(static_cast<std::size_t>(ncolours));
    for (int j = 0; j < n; j++) groups[colour[j]].push_back(j);
    return groups;
}

void difference_increment(Vec& dl, const Vec& y, const Vec& threshold) {
    const std::size_t n = y.size();
    for (std::size_t i = 0; i < n; i++) {
        double d = JAC_SQRT_EPS * sv::jl_max(std::fabs(y[i]), threshold[i]);
        d = d == 0 ? JAC_SQRT_EPS : d;
        const double moved = (y[i] + d) - y[i];
        dl[i] = moved == 0 ? d : moved;
    }
}

std::vector<std::vector<I32>> group_entries(const Pattern& p, const ColumnGroups& groups) {
    std::vector<I32> colour(static_cast<std::size_t>(p.n), -1);
    for (std::size_t c = 0; c < groups.size(); c++)
        for (I32 j : groups[c]) colour[j] = static_cast<I32>(c);
    std::vector<std::vector<I32>> out(groups.size());
    for (std::size_t q = 0; q < p.col_of.size(); q++) {
        const I32 c = colour[p.col_of[q]];
        if (c >= 0) out[c].push_back(static_cast<I32>(q));
    }
    return out;
}

DifferenceWork::DifferenceWork(const Pattern* p, const ColumnGroups* groups, int n)
    : dl(static_cast<std::size_t>(n), 0.0), ytry(static_cast<std::size_t>(n), 0.0), fg(static_cast<std::size_t>(n), 0.0) {
    if (p != nullptr && groups != nullptr) entries = group_entries(*p, *groups);
}

}  // namespace kompartment
