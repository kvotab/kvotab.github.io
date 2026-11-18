// df/dy for the implicit solvers: its structure, a colouring, and values
// differenced through it (engine/jacobian.py: Pattern, colour_columns,
// difference_increment, difference_jacobian, _group_entries).

#pragma once

#include <vector>

#include "solvers/types.hpp"

namespace kompartment {

/// A square sparsity pattern in compressed columns: counted from zero, the rows
/// sorted within each column, no duplicates. `col_of[p]` is the column of entry `p`.
struct Pattern {
    int n = 0;
    std::vector<I32> colptr;
    std::vector<I32> rowval;
    std::vector<I32> col_of;

    Pattern() = default;
    /// The pattern of the (row, col) pairs given (counted from zero; duplicates allowed).
    Pattern(int n, const std::vector<I32>& rows, const std::vector<I32>& cols);

    /// The number of entries.
    std::size_t nnz() const noexcept { return rowval.size(); }
};

/// Groups of columns that share no row.
using ColumnGroups = std::vector<std::vector<I32>>;

/// Groups of columns that share no row: greedy, largest degree first, ties in
/// column order (`colourColumns`).
ColumnGroups colour_columns(const Pattern& p);

/// sqrt(eps) times the larger of |y_j| and the threshold, rounded to what the
/// addition actually changed (into `dl`).
void difference_increment(Vec& dl, const Vec& y, const Vec& threshold);

/// The entries of each colour, in the pattern's order (`_group_entries`).
std::vector<std::vector<I32>> group_entries(const Pattern& p, const ColumnGroups& groups);

/// What differencing through a pattern needs, made once for a solve: the groups'
/// entries, the increments, the shifted state and the derivative at it.
struct DifferenceWork {
    std::vector<std::vector<I32>> entries;
    Vec dl;
    Vec ytry;
    Vec fg;

    DifferenceWork() = default;
    DifferenceWork(const Pattern* p, const ColumnGroups* groups, int n);
};

/// One-sided differences through the pattern, one evaluation of `f(out, t, y)`
/// per colour, into the pattern's values `out` (`differenceJacobian`).
template <class F>
void difference_jacobian(Vec& out, F&& f, double t, const Vec& y, const Vec& f0, const Pattern& p,
                         const ColumnGroups& groups, const Vec& threshold, DifferenceWork& w) {
    difference_increment(w.dl, y, threshold);
    const Vec& dl = w.dl;
    Vec& ytry = w.ytry;
    ytry = y;
    const I32* rowval = p.rowval.data();
    const I32* col_of = p.col_of.data();
    for (std::size_t g = 0; g < groups.size(); g++) {
        const std::vector<I32>& group = groups[g];
        const std::vector<I32>& entries = w.entries[g];
        for (I32 j : group) ytry[j] = ytry[j] + dl[j];
        f(w.fg, t, ytry);
        const Vec& fg = w.fg;
        for (I32 q : entries) {
            const I32 r = rowval[q];
            out[q] = (fg[r] - f0[r]) / dl[col_of[q]];
        }
        for (I32 j : group) ytry[j] = y[j];
    }
}

/// The same, into a new vector (Python's `difference_jacobian`).
template <class F>
Vec difference_jacobian(F&& f, double t, const Vec& y, const Vec& f0, const Pattern& p, const ColumnGroups& groups,
                        const Vec& threshold) {
    Vec out(p.nnz(), 0.0);
    DifferenceWork w(&p, &groups, p.n);
    difference_jacobian(out, f, t, y, f0, p, groups, threshold, w);
    return out;
}

}  // namespace kompartment
