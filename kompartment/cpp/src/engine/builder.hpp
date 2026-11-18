// Builds a runnable system from a Project (`buildSystem` in src/sim/builder.js,
// as the Python and Julia engines' builders port it).
//
// The state vector, the parameter vector and the algebraic slots are laid out
// exactly as the application lays them out -- same order, same offsets -- so
// a state or a slot can be compared with the application's one for one. Every
// equation becomes a statement over all the indices it is written at;
// statements of the same shape that do not read one another are merged; and
// the derivative is a list of phases of (target, value) contributions in the
// order the application adds them:
//
//     dC[i]/dt = sum(inflows) - sum(outflows) + sources
//                - lambda[m] * C[i] + sum over parents p (lambda * ratio * C[i, m := p])
//
// Every index here is the application's, counted from 0.

#pragma once

#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#include "engine/farfield_domain.hpp"
#include "engine/indexspace.hpp"
#include "engine/lookup.hpp"
#include "engine/project.hpp"
#include "engine/recorders.hpp"
#include "engine/tree.hpp"
#include "engine/userfunctions.hpp"
#include "lang/ast.hpp"
#include "util/json.hpp"

namespace kompartment {

/// What a part of the engine not yet carried across raises.
struct NotSupported : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// A model that cannot be built into equations; `block_name` and `setting` say where.
struct BuildError : std::runtime_error {
    std::optional<std::string> block_name;
    std::optional<std::string> setting;
    /// `block` may be `Block#setting`: the message is then said of the block's setting in words.
    explicit BuildError(const std::string& message, const std::optional<std::string>& block = std::nullopt);
};

/// A builder message with its `'Block#setting'` names said in words.
std::string in_words(const std::string& message);

inline constexpr const char* UNINDEXED = "not by nuclide";
inline constexpr double WINDOW_TAIL = 1e-3;
inline constexpr double AVOGADRO_AVAILABILITY = 6.02214076e23;
const std::vector<std::string>& budget_terms();   // in, out, decay, ingrowth, explicit, between

struct Entry;
using EntryPtr = std::shared_ptr<Entry>;
struct FarfieldPath;

/// What a far-field path's state block is laid out as.
struct FarfLayout {
    std::optional<FarfStructure> structure;   // none for a semi-analytical path
    bool laplace = false;
    int nnuc = 1;
    std::vector<std::string> other_dims;
    int other_width = 1;
    int ncells = 0;
    int m_idx = -1;                           // which dimension the chain runs along, -1 for none
    std::optional<std::string> list_name;
    std::vector<int> dim_off;
    std::vector<int> single_off;
};

/// The mass-balance audit's rows: a family per material and one for what is not by nuclide.
struct Budget {
    struct Member {
        std::string name;
        int base, width;
        std::vector<int> fam_of;
    };
    int base = 0;
    int nfam = 0;
    std::vector<std::string> families;
    std::vector<std::string> terms;
    std::vector<Member> members;
};

/// A transfer's availability: its scheme and the slots of the scheme's operands.
struct Availability {
    Json scheme;
    std::vector<std::pair<std::string, EntryPtr>> operands;
};

/// A layout entry: a state block, a parameter, an algebraic slot range, and the holders
/// the builder keeps beside them (a set of waste packages, an event, a recorder). The
/// fields every entry has come first; the rest are what only some kinds carry.
struct Entry {
    std::string name;
    std::optional<std::string> local_name;
    std::string system;
    std::string kind;
    Json block;                      // the normalised block, or a holder; null for none
    std::optional<std::string> value_key;
    std::vector<std::string> dims;
    int base = 0;
    int width = 0;
    bool hidden = false;
    std::vector<std::string> equations;
    std::vector<ENodePtr> asts;
    bool uniform = true;
    std::vector<std::string> reads_alg;
    int level = 0;
    int cls = 0;
    std::vector<std::string> needs;

    // --- a far-field path -------------------------------------------------------------
    std::shared_ptr<FarfLayout> farf;       // on the path's state entry
    EntryPtr path;                          // on its release slot: the path
    int farf_index = -1;
    EntryPtr alg_release;
    std::optional<int> decay_slot;
    // --- waste packages and events ----------------------------------------------------
    std::string role, qname, unit;          // a state of packages: intact or exposed
    std::string q;
    EntryPtr intact, exposed;
    std::string failure;
    struct Disrupted {
        EntryPtr D, share;
    };
    std::vector<Disrupted> disrupted;
    std::vector<std::pair<std::string, EntryPtr>> setting;   // a setting's slot, by key
    EntryPtr hazard_slot, release_slot, lambda_slot;
    EntryPtr waste;                         // on a hazard or release slot: the packages
    EntryPtr event;                         // on an event's rate slot: the event
    EntryPtr entry;                         // an event's state; a recorder's own slot
    std::string timing;
    Json actions;
    int number = -1;                        // which event, from 0
    std::vector<double> sampled_times;
    std::vector<EntryPtr> shares;
    std::vector<int> fired_by;
    // --- the audit ---------------------------------------------------------------------
    std::shared_ptr<Budget> budget;
    // --- lookup tables and their distributed points -------------------------------------
    Tup index;
    int off = 0;
    int point = 0;
    double at = 0, value = 0;
    Json spec;
    int slot = -1;
    int tab = -1;
    int row = -1;
    std::optional<std::string> argument;
    // --- algebraic slots ------------------------------------------------------------------
    std::shared_ptr<Availability> availability;
    std::optional<std::string> transfer;    // an availability operand's transfer
    std::optional<std::string> state_name;  // a dy/dt term's compartment
    bool single = false;
    std::optional<std::string> over;
    std::vector<std::string> dropped;
    // --- recorders ------------------------------------------------------------------------
    std::vector<std::pair<std::string, EntryPtr>> aux;
    int mem = -1;
    EntryPtr state;                         // a running mean's summed state
    EntryPtr recorder;                      // on a recorder's slot: the recorder
    int event_base = -1;

    /// What a block occupies by being what it is, worked out once.
    struct Context {
        std::vector<std::pair<std::string, std::optional<std::string>>> items;
        /// The index at a key; none when the key is absent or holds nothing.
        std::optional<std::string> at(std::string_view key) const {
            for (const auto& it : items)
                if (it.first == key) return it.second;
            return std::nullopt;
        }
    };
    bool context_made = false;
    std::optional<Context> context;

    const EntryPtr* setting_at(std::string_view key) const {
        for (const auto& it : setting)
            if (it.first == key) return &it.second;
        return nullptr;
    }
    const EntryPtr& aux_at(std::string_view key) const {
        for (const auto& it : aux)
            if (it.first == key) return it.second;
        throw std::logic_error("no such slot");
    }
};

/// What a statement of special code does, when it is not an expression.
struct Special {
    enum class Kind : unsigned char { FarfieldRelease, MinMax, RunningMean, Snapshot, Delay };
    Kind kind;
    int index = 0;            // a far-field path, from 0
    bool laplace = false;
    std::vector<int> out;     // slots written
    std::vector<int> mem;     // recorders read
    std::vector<int> arg;     // the target slot (min/max, running mean) or the delay slot (delay)
    std::vector<int> state;   // a running mean's summed state
};

/// One statement of a pass: `array[out] = tree` over `width` elements, or special code.
struct Stmt {
    enum class Array : unsigned char { X, Y0, State, Clock };
    int out = 0;              // the slot written, when one for every element
    IntVec outs;              // one per element, when they differ
    TNodePtr tree;
    int width = 0;
    EntryPtr block;
    std::pair<int, int> level{0, 0};
    bool mergeable = true;
    std::shared_ptr<const Special> special;
    Array array = Array::X;
    bool multiply = false;

    /// The slot each element writes.
    std::vector<int> out_indices() const {
        if (outs) return *outs;
        return std::vector<int>(static_cast<std::size_t>(width > 1 ? width : 1), out);
    }
};

/// One phase of the derivative's assembly, in the order the application adds the terms.
/// Which fields mean what depends on `kind`:
///
/// - Transfers -- `tgt` the state each term goes into, `a` the flux it is, `f` its sign;
/// - X         -- `tgt` and `a`, the algebraic slot added there;
/// - Waste     -- `tgt` the intact inventory, `a` the exposed one, `s1` the hazard slot,
///                `b` the release slots, `c` the budget's `out` slots (empty without the audit);
/// - Move      -- `tgt` the states moved out of, `a` where they go (empty: nowhere), `s1`
///                the event's rate slot, `s2` its share slot;
/// - Mean      -- `tgt` the summed states, `a` the target slots, `s1` the first recorder;
/// - Coef      -- `tgt`, `f` the coefficient, `a` the state it multiplies;
/// - Farf      -- `s1` the path.
struct Phase {
    enum class Kind : unsigned char { Transfers, X, Waste, Move, Mean, Coef, Farf };
    Kind kind;
    std::vector<int> tgt, a, b, c;
    std::vector<double> f;
    int s1 = -1, s2 = -1;
};

/// What a jump in the state does, one operation at a time.
struct JumpOp {
    enum class Kind : unsigned char {
        Count,   // y[slot] += 1
        Fail,    // packages failing: a share of the intact inventory fails; the instant release
                 // fraction goes on to `to`, the rest is exposed
        Move     // a share of a compartment moved, cell for cell, into another (or out of the model)
    };
    Kind kind;
    int slot = -1;
    int share_slot = -1;         // -1: all of them (share 1)
    std::vector<int> intact, exposed, irf;
    std::vector<int> from, to;   // `to` empty: nowhere the model holds
    std::vector<int> budget;     // the audit's `out` (empty without it)
};

struct JumpSpec {
    std::string name;
    std::vector<JumpOp> ops;
    std::optional<int> slot;     // the algebraic slot holding its time; none: drawn times
    std::string text;
    int index = -1;              // an event's number, -1 for packages
    std::vector<int> fired_by;   // the event slots whose firing applies it; empty: a corner or drawn times
};

/// The decay model flattened: per index its constant, and its (parent, coefficient) pairs.
struct DecayTables {
    std::vector<double> lam;
    std::vector<int> ioff, icnt, ipar;
    std::vector<double> icoef;
};
DecayTables decay_tables(const DecayModel& model, int size);

/// A trigger's crossing function, by slot.
struct EventSlot {
    int slot;
    int direction;
    std::string name;
    std::optional<Tup> index;
};
struct EventHandler {
    EntryPtr rec;
    int off;
    RecorderAction action;
};

/// What a reference reads.
enum class RefKind : unsigned char { State, Param, Alg, Table };
struct Located {
    RefKind kind;
    EntryPtr target;
    int index = 0;      // one for every element,
    IntVec indices;     // or one per element of the statement
};

using Positions = std::vector<std::vector<int>>;

/// Everything `buildSystem` works out for a project.
class Builder {
public:
    /// Builds `project` (a model with transports is expanded first, and that is the project kept).
    explicit Builder(std::shared_ptr<const Project> project);

    std::shared_ptr<const Project> project;
    const IndexSpace* space = nullptr;
    std::optional<std::string> material_list;
    DecayModel decay;
    std::optional<std::string> material_root;
    // states
    std::vector<EntryPtr> states;
    int nstate = 0;
    std::vector<EntryPtr> mean_states;
    std::vector<EntryPtr> farf_layout;
    std::vector<EntryPtr> waste_layout;
    std::unordered_map<std::string, EntryPtr> waste_by_name;
    std::vector<EntryPtr> disruption_layout;
    std::shared_ptr<Budget> budget;
    std::unordered_map<std::string, EntryPtr> state_by_name;
    std::unordered_map<std::string, EntryPtr> path_by_name;
    // parameters and tables
    std::vector<EntryPtr> param_layout;
    std::unordered_map<std::string, EntryPtr> param_by_name;
    std::vector<EntryPtr> point_layout;
    std::map<std::pair<std::string, int>, std::vector<EntryPtr>> points_by_entry;
    int nparam = 0;
    std::vector<double> P;
    std::vector<std::shared_ptr<LookupTable>> TAB;   // elements that share one list of points share its table
    std::vector<EntryPtr> lookup_layout;
    std::unordered_map<std::string, EntryPtr> table_by_name;
    // algebraic slots
    std::vector<EntryPtr> algebraic;
    int nalg = 0;
    std::unordered_map<std::string, EntryPtr> alg_by_name;
    std::vector<EntryPtr> dydt_slots;
    std::vector<std::shared_ptr<FarfieldPath>> FARF;
    std::vector<Recorder> MEM;
    std::vector<EntryPtr> recorders;
    UserFunctions functions;
    std::unordered_map<std::string, Json> unit_blocks;
    // events
    std::vector<EventSlot> event_slots;
    std::vector<signed char> event_direction;
    std::map<int, std::vector<EventHandler>> event_handlers;
    // statements
    std::unordered_set<std::string> self_reading;
    std::unordered_map<std::string, std::vector<std::shared_ptr<Stmt>>> alg_stmts;
    std::vector<std::shared_ptr<Stmt>> pass_stmts[3];
    std::vector<unsigned char> slot_class;
    std::unordered_set<std::string> on_state;
    std::unordered_set<std::string> on_clock;
    // the derivative
    std::vector<Phase> phases;
    int nflux = 0;
    std::vector<int> flux_rate;
    std::vector<int> flux_mbd;
    std::vector<int> flux_mbd_src;
    std::vector<std::string> decay_lists;
    struct Decaying {
        EntryPtr state;
        int m;      // which dimension, from 0
        int slot;
    };
    std::vector<Decaying> decaying;
    std::unordered_map<std::string, DecayTables> DEC_tables;
    std::vector<DecayTables> DEC;
    std::vector<JumpSpec> jump_specs;
    bool has_derivative_stmts = false;      // false: nothing is left out of the moving pass
    std::unordered_set<std::string> derivative_blocks;
    std::vector<std::shared_ptr<Stmt>> derivative_stmts;
    std::vector<std::shared_ptr<Stmt>> initial_before;
    std::vector<std::shared_ptr<Stmt>> initial_stmts;

    // --- what the rest of the engine asks of a builder ---------------------------------
    std::vector<std::string> dims_of(const Json& block) const;
    bool is_nuclide_dim(const std::string& d) const;
    Tup entry_tuple(const Json& block, const std::vector<std::string>& dims, int off) const;
    bool known(const std::string& n) const;
    EntryPtr call_target(const std::string& name, const std::string& system) const;
    EntryPtr target_entry(const std::string& name, const std::string& system) const;
    ENodePtr parse_model_equation(const std::string& text, const std::string& system, const std::string& owner) const;

    /// What a reference reads: its kind, the entry, and the index -- one, or one per
    /// element of the statement (`pos`, the positions of the statement's elements along
    /// `source_dims`; null with `fixed_tuple` given for one element at a named tuple).
    Located locate(const EntryPtr& owner, const std::string& owner_name, const std::vector<std::string>& source_dims,
                   const Positions* pos, const Tup* fixed_tuple, const ERef& ref);
    RefResolver make_resolver(const EntryPtr& owner, const std::vector<std::string>& source_dims, const Positions* pos,
                              const Tup* fixed_tuple);
    CallResolver make_call_resolver(const EntryPtr& owner, const std::vector<std::string>& source_dims, const Positions* pos,
                                    const Tup* fixed_tuple);

    /// Where a state block is read from inside `source_dims`: one offset per element.
    std::vector<int> state_offsets(const std::vector<std::string>& source_dims, const Positions& pos, const EntryPtr& entry,
                                   const std::string& owner, int width);
    std::vector<int> farf_inlet(const std::vector<std::string>& source_dims, const Positions& pos, const EntryPtr& entry,
                                const std::string& owner, int width);
    std::vector<int> family_of(const std::vector<std::string>& dims, const Positions& pos, int width) const;

private:
    void layout_states();
    void layout_parameters();
    void layout_tables();
    void layout_algebraic();
    EntryPtr add_algebraic(const std::string& name, const std::string& kind, const Json& block,
                           const std::optional<std::string>& value_key, const std::vector<std::string>* over = nullptr);
    void prepare_parsing();
    void parse_all();
    void order_algebraic();
    void levels();
    void events();
    void generate_algebraic();
    std::vector<std::shared_ptr<Stmt>> statements_for(const EntryPtr& a);
    TNodePtr resolve_stmt_tree(const EntryPtr& a, const ENode& ast, const std::vector<std::string>& dims, const Positions* pos,
                               const Tup* tup);
    std::vector<std::shared_ptr<Stmt>> by_equation(const EntryPtr& a);
    std::vector<std::shared_ptr<Stmt>> groups(const EntryPtr& a, const std::set<std::string>& flat_set);
    std::vector<std::shared_ptr<Stmt>> availability_stmts(const EntryPtr& a);
    void classes();
    void derivative_reads();
    void assembly();
    void jumps();
    void initial_state();

    struct IndexOperation {
        ENodePtr ast;
        std::string text;
        std::optional<std::string> over;
        std::vector<std::string> dropped;
    };
    IndexOperation index_operation_ast(const EntryPtr& a, const std::string& target) const;
    IndexOperation aggregate_ast(const EntryPtr& a, const std::vector<std::string>& targets) const;
    std::vector<int> endpoint_family(const EntryPtr& entry, const std::vector<std::string>& dims, const Positions& pos, int width) const;
    std::string family_key(const EntryPtr& entry, const std::vector<std::string>& dims) const;
    std::vector<int> budget_at(std::string_view term, const std::vector<int>& fam) const;
    std::pair<EntryPtr, EntryPtr> move_ends(const EntryPtr& D, const Json& action) const;
    std::optional<JumpOp> fail_op(const EntryPtr& W, int share_slot);
};

// --- helpers over the index space, shared with the rest of the engine --------------------------------

Tup tuple_by_list(const IndexSpace& space, const std::vector<std::string>& dims, int offset);
/// The enabled position of `dim` for a tuple, through related lists, or none.
std::optional<int> position_in(const IndexSpace& space, const std::string& dim, const Tup& tup);
std::string describe_tuple(const Tup& tup);

/// A statement over several elements as one statement per element, in order.
std::vector<std::shared_ptr<Stmt>> split_stmt(const std::shared_ptr<Stmt>& s);

/// Statements at the same level with the same shape, merged into one each: the order of
/// the result is by level; within a level, merged groups keep the position of their first
/// statement. Statements that may not be merged stay where they are.
std::vector<std::shared_ptr<Stmt>> merge_statements(const std::vector<std::shared_ptr<Stmt>>& stmts);

}  // namespace kompartment
