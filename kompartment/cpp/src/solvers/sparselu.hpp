// The application's sparse LUs (src/ode/core/sparse.js, refactor.js, blocks.js),
// as the Python engine has them (engine/solvers/sparselu.py).
//
// For a sparse iteration matrix the application chooses between a
// Gilbert-Peierls LU in two column orders, the LU that keeps its pivots and
// that LU a block at a time, on one real factorisation of each. These are
// those LUs and that choice, step for step -- the same pivots, the same
// eliminations in the same order, one rounding per operation and no fused
// multiply-adds -- so a sparse matrix is factorised and solved with as the
// application and the Python engine do it, to the last bit.
//
// Every index held here -- a state, a slot, a step, a place in a list -- is
// counted from zero, as in the application and the Python engine, so the three
// read side by side and hold the same numbers; -1 is none. Indices are held in
// 32 bits (a slot, a row, a step), places in the factors' growing lists in 64.

#pragma once

#include <cstdint>
#include <utility>
#include <vector>

#include "solvers/types.hpp"

namespace kompartment {

namespace slu {

// refactor.js: a pivot is chosen among the entries at least this share of the
// largest in their column, and kept while none below it is more than
// 1/KEEP_THRESHOLD times it; the SEARCH_COLUMNS sparsest columns are searched;
// and past REORDER_GROWTH times the work of the last choice made from the
// start, the pivots are chosen from the start again.
constexpr double PIVOT_THRESHOLD = 0.1;
constexpr double KEEP_THRESHOLD = 0.01;
constexpr int SEARCH_COLUMNS = 16;
constexpr double REORDER_GROWTH = 1.2;
// refactor.js: the record holds one index per multiply-add; past this many
// `auto` leaves the matrix to the Gilbert-Peierls LU.
constexpr double OPS_BUDGET = 4e6;

// What a matrix is factorised with: the caller's dense LU (`auto` chose it),
// the Gilbert-Peierls LU, the kept-pivot LU whole, or a block at a time.
constexpr int DENSE = 0;
constexpr int SPARSE = 1;
constexpr int WHOLE = 2;
constexpr int BLOCKS = 3;
// The column orders, as `info["ordering"]` names them.
extern const char* const ORDERINGS[6];
constexpr int NATURAL = 0;
constexpr int RCM = 1;
constexpr int MARKOWITZ = 2;
constexpr int NATURAL_COLUMNS = 3;
constexpr int RCM_COLUMNS = 4;
constexpr int BLOCKED = 5;
// The modes `iterationMatrix` takes a sparse LU in.
constexpr int AUTO = 0;
constexpr int REFACTOR = 1;
constexpr int SPARSE_MODE = 2;
// Which LU the latest factorisation is in: the kept-pivot one, or what a
// matrix it declined went to -- or none, the latest formation having failed
// (or none made yet, where there was no trial), which no solve reads.
constexpr int KEPT = 0;
constexpr int BY_SPARSE = 1;
constexpr int BY_DENSE = 2;
constexpr int NONE_MADE = 3;
// A formation's outcome: factorised, singular, or a value not a number.
constexpr int OK = 0;
constexpr int SINGULAR = 1;
constexpr int NONFINITE = 2;

// --- Mass - a*J in CSC (`makeMiterBuilder`) -----------------------------------------------------------

/// The pattern of Mass - a*J -- J's with the diagonal, each column's rows in
/// order -- and where J's entries (`jtom`) and the diagonal sit in it.
struct MiterStructure {
    std::vector<I32> mp;
    std::vector<I32> mi;
    std::vector<I32> jtom;
    std::vector<I32> diag;
};
MiterStructure miter_structure(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx);

/// mx := the values of Mass - a*J (`update`).
void miter_update(Vec& mx, double a, const Vec& values, const Vec& mass, bool has_mass, const std::vector<I32>& jtom,
                  const std::vector<I32>& diag);

// --- Gilbert-Peierls LU (`SparseLU`) ------------------------------------------------------------------

/// The Gilbert-Peierls LU: the row each step pivots on (`pinv` by row, `perm`
/// by step), the column order (`qcol`, used where `has_q`), the depth-first
/// search's work, L by columns with the unit diagonal first and U with the pivot
/// last, a solve's work, and how the latest factorisation went.
struct GP {
    int n = 0;
    std::vector<I32> pinv;
    std::vector<I32> perm;
    std::vector<I32> qcol;
    bool has_q = false;
    Vec x;
    std::vector<I32> xi;
    std::vector<I32> stack;
    std::vector<I64> pstack;
    std::vector<I32> mark;
    I32 stamp = 0;
    std::vector<I64> Lp;
    std::vector<I32> Li;
    Vec Lx;
    std::vector<I64> Up;
    std::vector<I32> Ui;
    Vec Ux;
    Vec t;
    I64 lnz = 0;
    I64 unz = 0;
    I64 flops = 0;
    bool singular = false;
    bool nonfinite = false;
    bool over = false;
    I32 fail_column = -1;
    I32 fail_original = -1;

    GP() = default;
    explicit GP(int n);
};

/// P*A*Q = L*U, Q the column order `q` where `has_q` (`factorize`); stops as
/// soon as L and U hold more than `limit` entries, `over` set.
void gp_factorize(GP& g, const std::vector<I32>& ap, const std::vector<I32>& ai, const Vec& ax,
                  const std::vector<I32>& q, bool has_q, double limit);

/// A*x = b into `out`: P b, then L \ ., then U \ ., through Q (`solve`).
void gp_solve(GP& g, const Vec& b, Vec& out);

// --- reverse Cuthill-McKee, and the blocks ------------------------------------------------------------

/// Reverse Cuthill-McKee on the pattern of A + A' (`reverseCuthillMcKee`): each
/// component from its node of least degree, neighbours by degree, ties by number.
std::vector<I32> rcm_order(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx);

/// The strongly connected components of the pattern's graph, an edge from
/// column j to row i for each entry (i, j) off the diagonal, numbered in the
/// order Tarjan's algorithm closes them (`blockTriangular`): block upper
/// triangular. Without recursion. The number of blocks, and each state's.
std::pair<I32, std::vector<I32>> block_triangular(int n, const std::vector<I32>& colptr,
                                                  const std::vector<I32>& rowidx);

// --- the LU that keeps its pivots (`RefactorLU`) ------------------------------------------------------

/// The kept-pivot LU: the slots (every entry of the matrix and its fill, by
/// row and column, the pattern's and the diagonal's places among them), the
/// record of the steps, the factor as a solve reads it, and the work of choosing
/// -- each row's and column's slots in one pool, a list each.
struct RF {
    int n = 0;
    I32 nnzj = 0;
    std::vector<I32> columns;
    bool has_columns = false;
    std::vector<I32> slot_row;
    std::vector<I32> slot_col;
    std::vector<I32> jslot;
    std::vector<I32> dslot;
    I32 nbase = 0;
    I32 nslots = 0;
    Vec V;
    std::vector<I32> pr;
    std::vector<I32> pc;
    std::vector<I32> pslot;
    std::vector<I32> lstart;
    std::vector<I32> ustart;
    std::vector<I64> tstart;
    std::vector<I32> fill_start;
    std::vector<I32> lslot;
    std::vector<I32> lrow;
    std::vector<I32> uslot;
    std::vector<I32> ucol;
    std::vector<I32> T;
    Vec lval;
    std::vector<I32> lstep;
    Vec uval;
    std::vector<I32> ustep;
    Vec dval;
    std::vector<I32> row_step;
    std::vector<I32> col_step;
    bool valid = false;
    I64 ops = 0;
    I64 nnz = 0;
    I64 repivots = 0;
    I64 full_ops = 0;
    double limit = sv::INF;
    std::vector<std::uint8_t> row_active;
    std::vector<std::uint8_t> col_active;
    std::vector<I32> rc;
    std::vector<I32> cc;
    std::vector<I32> head;
    std::vector<I32> nxt;
    std::vector<I32> prv;
    std::vector<I32> at;
    std::vector<I32> at_stamp;
    std::vector<I64> row_start;
    std::vector<I32> row_len;
    std::vector<I32> row_cap;
    std::vector<I64> col_start;
    std::vector<I32> col_len;
    std::vector<I32> col_cap;
    std::vector<I32> pool;
    I64 pool_top = 0;
    Vec z;
};

/// For J's pattern (`colptr`, `rowidx`, counted from zero); `columns` a fixed
/// column order where `has_columns`, else columns chosen by threshold Markowitz too.
RF rf_new(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx, const std::vector<I32>& columns,
          bool has_columns);

/// Factorises Mass - a*J; false when it cannot be done with pivots that pass the test (`factor`).
bool rf_factor(RF& r, double a, const Vec& values, const Vec& mass, bool has_mass);

/// Against the latest factorisation, into `out` (`solve`).
void rf_solve(RF& r, const Vec& b, Vec& out);

// --- a block at a time (`BlockLU`) --------------------------------------------------------------------

/// The block LU: the blocks and their states, the entries between blocks, a
/// kept-pivot LU for each block of more than one state (`lu_of`, -1 for one of
/// one state) and where J holds its entries, and the factor laid out by step in
/// the order the solve takes the blocks.
struct BK {
    int n = 0;
    I32 nblocks = 0;
    std::vector<I32> start;
    std::vector<I32> member;
    std::vector<I32> off_ptr;
    std::vector<I32> off_row;
    std::vector<I32> off_pos;
    std::vector<I32> diag_pos;
    std::vector<I32> lu_of;
    std::vector<RF> lus;
    std::vector<I32> pos_ptr;
    std::vector<I32> pos;
    Vec b_values;
    Vec b_mass;
    std::vector<I32> base;
    std::vector<I32> row_of_step;
    std::vector<I32> col_of_step;
    std::vector<I32> step_of_row;
    std::vector<I32> seg_start;
    std::vector<I32> seg_block;
    std::vector<I64> Lp;
    std::vector<I64> Up;
    std::vector<I32> Li;
    Vec Lx;
    std::vector<I32> Ui;
    Vec Ux;
    Vec D;
    /// Without parity: 1/D, so that a solve multiplies where it would divide.
    Vec Dinv;
    /// Set where the solve need not give the other engines' bits (no parity): a pivot
    /// multiplied by its reciprocal, products fused into the sums.
    bool quick = false;
    /// A run of blocks of one state each, solved level by level (see `bk_new` and
    /// `bk_solve`): the step now at each place of the order the blocks came in; the
    /// entries a step of the run waits for, by step, in that order (`pull`); and the
    /// entries from a run to the segments after it, by the place of their column in
    /// that order (`push`) -- the step read or written, where `off_x` holds the value,
    /// and the value, copied after every factorisation.
    std::vector<I32> run_orig;
    std::vector<I32> pull_p, pull_step, pull_at;
    Vec pull_x;
    std::vector<I32> push_p, push_step, push_at;
    Vec push_x;
    I32 npull = 0;
    std::vector<I32> off_p;
    std::vector<I32> off_step;
    std::vector<I32> off_at;
    Vec off_x;
    Vec zs;
    I64 laid_out = -1;
    bool valid = false;
    I64 ops = 0;
    double limit = sv::INF;
    I64 nnz = 0;
};

BK bk_new(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx, I32 nblocks,
          const std::vector<I32>& block);

/// Times a block's pivots were chosen again, over every block.
I64 bk_repivots(const BK& bk);

/// Factorises Mass - a*J a block at a time (`factor`); false when a block
/// cannot be done with pivots that pass the test, or a value is not a number.
bool bk_factor(BK& bk, double a, const Vec& values, const Vec& mass, bool has_mass);

/// Against the latest factorisation, the blocks from the last to the first,
/// each one's entries between blocks taken off the right-hand side as soon as its
/// unknown is known (`solve`).
void bk_solve(BK& bk, const Vec& b, Vec& out);

}  // namespace slu

// --- the iteration matrix (`iterationMatrix`) ---------------------------------------------------------

/// A sparse iteration matrix as `iterationMatrix` makes it: J's pattern, the
/// structure of Mass - a*J in CSC (`makeMiterBuilder`), the Gilbert-Peierls LU and
/// its column order, the kept-pivot LU (whole, or a block at a time), the dense
/// LU a declined matrix goes to where the factor fills in, and `info`.
///
/// Made in `mode` (`slu::AUTO`, `slu::REFACTOR`, `slu::SPARSE_MODE`) from J's
/// pattern (`colptr`, `rowidx`, counted from zero) and its values at the start
/// -- or, its kind `slu::DENSE`, the word that `auto` would factorise it densely.
/// One real factorisation of each candidate decides: reverse Cuthill-McKee's
/// column order or the model's own, by fill; the kept-pivot LU a block at a
/// time, whole by threshold Markowitz, or whole in that column order, where it
/// costs no more than the alternative; the dense LU where the searching factor
/// fills in; the Gilbert-Peierls LU otherwise.
struct SparseLUMatrix {
    int n = 0;
    int kind = slu::SPARSE;
    std::vector<I32> colptr;
    std::vector<I32> rowidx;
    Vec masked;
    Vec mass;
    bool has_mass = false;
    std::vector<I32> mp;
    std::vector<I32> mi;
    Vec mx;
    std::vector<I32> jtom;
    std::vector<I32> diag_pos;
    slu::GP gp;
    std::vector<I32> q;
    bool has_q = false;
    slu::RF whole;
    slu::BK blocks;
    bool fills_in = false;
    int current = slu::NONE_MADE;
    Vec dense;
    std::vector<I32> dpiv;
    I64 fill = 0;
    I64 repivots = 0;
    I64 fallbacks = 0;
    I64 trial_repivots = 0;
    int ordering = slu::NATURAL;
    I32 fail_column = -1;
    double fail_value = 0.0;
    bool fail_nonfinite = false;

    SparseLUMatrix(int n, std::vector<I32> colptr, std::vector<I32> rowidx, const Vec& values, Vec mass,
                   bool has_mass, int mode, double dense_fill, bool too_big, bool blocks);
};

namespace slu {

/// Factorises Mass - a*J, the rows `held` marks (where not null) as rows of
/// the identity: `OK`, `SINGULAR` or `NONFINITE`, with the column (and the
/// value) in `fail_column` and `fail_value`. A matrix the kept-pivot LU
/// declines goes to the LU that would otherwise have been used, whose answer is
/// final.
int form(SparseLUMatrix& sw, double a, const Vec& values, const std::uint8_t* held);

/// Against the latest formation, into `out` (distinct from `b`): NaN after one
/// that failed, which the solvers stop at -- the application's answer there is
/// whatever a half-made factor gives.
void solve(SparseLUMatrix& sw, const Vec& b, Vec& out);

/// Which LU, as `info["lu"]` names it.
const char* lu_name(const SparseLUMatrix& sw);

}  // namespace slu

}  // namespace kompartment
