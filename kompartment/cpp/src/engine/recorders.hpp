// The blocks that remember: min/max, running mean, snapshot, delay -- and
// triggers (src/domain/recorders.js, src/sim/history.js). A remembering block
// is not a function of the state: it keeps (time, value) pairs recorded as the
// solver accepts steps, and reads them back.

#pragma once

#include <limits>
#include <string>
#include <string_view>
#include <vector>

namespace kompartment {

const std::vector<std::string>& recorder_kinds();       // min_max, running_mean, snapshot, delay, trigger
bool is_remembering_kind(std::string_view kind);         // all but trigger
std::string recorder_collection(std::string_view kind);
int direction_sign(std::string_view direction);          // rising 1, falling -1, both 0
/// The settings of a kind that name a trigger, and the ones that are equations.
std::vector<std::string> event_fields(std::string_view kind);
std::vector<std::string> equation_fields(std::string_view kind);

enum class RecorderAction : unsigned char { Reset, Start, Stop, Snapshot };
RecorderAction event_action(std::string_view field);

/// A growing list of (time, value) pairs, read back by time.
struct History {
    std::vector<double> t, v;

    std::size_t size() const { return t.size(); }
    void clear() {
        t.clear();
        v.clear();
    }
    double last_time() const { return t.empty() ? -std::numeric_limits<double>::infinity() : t.back(); }
    double last_value() const { return v.empty() ? 0.0 : v.back(); }
    void add(double time, double value);
    /// The value recorded at or before `time`.
    double hold(double time) const;
    /// The value at `time`, on the straight line between the two records around it.
    double lerp(double time) const;

private:
    /// The index of the last time at or before `time`, -1 when there is none.
    long below(double time) const;
};

enum class RecorderKind : unsigned char { MinMax, RunningMean, Snapshot, Delay };

/// One remembering block at one index tuple (`MEM[k]`).
struct Recorder {
    RecorderKind kind = RecorderKind::MinMax;
    History history;
    int sign = 1;
    bool starts_recording = true;
    bool recording = true;
    double total_time = 0.0;
    double last_time = 0.0;
    double reset_sum = 0.0;

    Recorder() = default;
    Recorder(std::string_view kind_name, std::string_view operation = "max", bool recording_ = true);

    void prime(double t0, double seed);
    void store(double t, double current);
    void fire(RecorderAction what, double t, double target, double summed = 0.0);

    double extreme(double t, double target) const;
    double held(double t) const { return history.hold(t); }
    double delayed(double t, double lag) const { return history.lerp(t - lag); }
    double elapsed_at(double t) const { return recording ? total_time + t - last_time : total_time; }
    double mean_of(double t, double summed, double target) const;
};

}  // namespace kompartment
