// The model's passes, evaluated.
//
// Each pass -- the slots that never change, those that follow the clock alone,
// those that read the state, the initial state -- is a list of statements,
// `array[out] = tree` over the elements the statement is written at. The
// other engines turn them into source code and have a compiler make machine
// code of it; this one compiles them, in microseconds, into programs of
// vector instructions and runs those: a statement over many elements is
// worked out a block of elements at a time, each instruction one tight loop
// over the block, its operands a slot shared by every element, a run of
// consecutive slots read where they lie, or slots gathered through an index
// vector. Nothing waits for a compiler, and a statement over thousands of
// nuclides costs per element what compiled code costs.
//
// The arithmetic is the other engines' operation for operation -- no fused
// multiply-adds, the C library's transcendental functions, numpy's min and
// max and its short cuts in a power -- so a pass gives their numbers to the
// last bit. A statement whose conditional guards something that can refuse
// its arguments (a transport operation, an interpolation over arguments) is
// worked out one element at a time, only the branch taken, as they do.

#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "engine/builder.hpp"
#include "engine/lookup.hpp"
#include "engine/recorders.hpp"
#include "engine/tree.hpp"

namespace kompartment {

struct FarfieldPath;

/// What a model's passes read besides the state, the algebraic slots and the parameters.
struct ModelData {
    std::vector<std::shared_ptr<LookupTable>> TAB;
    std::vector<Recorder> MEM;
    std::vector<double> DIS;
    double T0 = 0, T1 = 0;
    std::vector<std::shared_ptr<FarfieldPath>> FARF;
};

/// Where a pass is evaluated.
struct EvalContext {
    double t;
    double* y;
    double* X;
    const double* P;
    ModelData* D;
};

/// One element of a tree, worked out by walking it: the reference the programs are
/// checked against, and how a statement that must not evaluate an untaken branch is run.
double eval_tree(const TNode& tree, std::size_t element, const EvalContext& ctx);

/// A pass compiled: `run` works every statement out in order.
class Program {
public:
    Program() = default;
    explicit Program(const std::vector<std::shared_ptr<Stmt>>& statements);

    /// `work` is scratch the caller keeps between calls (one per thread).
    void run(EvalContext& ctx, std::vector<double>& work) const;
    std::size_t size() const { return stmts_.size(); }
    bool empty() const { return stmts_.empty(); }
    /// How many elements the pass writes.
    std::size_t elements() const { return elements_; }

    struct Operand {
        enum Kind : std::uint8_t { Const, Vec, T, T0, T1, Scalar, Run, Reg };
        Kind kind = Const;
        std::uint8_t array = 0;   // 0 y, 1 P, 2 X, 3 DIS
        std::int32_t index = 0;   // a constant, a vector's start, a slot, a run's first slot, a register
    };
    struct Instr {
        std::uint8_t op = 0;
        std::uint8_t fn = 0;
        std::uint8_t flag = 0;
        std::int32_t dst = 0;
        Operand a, b, c;
        std::int32_t args = 0;    // the first of its operands, for a function of many
        std::int32_t nargs = 0;
        std::int32_t ints = 0;    // an index vector's start
    };
    struct Compiled {
        std::int32_t width = 0;
        std::int32_t first = 0, count = 0;   // its instructions
        Operand result;
        std::uint8_t array = 2;              // 0 y, 2 X
        bool multiply = false;
        std::uint8_t out_kind = 0;           // 0 one slot, 1 a run, 2 scattered
        std::int32_t out = 0;                // the slot, the run's first, or the index vector's start
        std::int32_t registers = 0;
        TNodePtr lazy;                       // worked out an element at a time
        std::shared_ptr<const Special> special;
    };

private:
    std::vector<Compiled> stmts_;
    std::vector<Instr> code_;
    std::vector<Operand> args_;
    std::vector<double> consts_;
    std::vector<double> vecs_;
    std::vector<std::int32_t> ints_;
    std::size_t elements_ = 0;
    std::int32_t most_registers_ = 0;
    friend struct ProgramCompiler;
};

}  // namespace kompartment
