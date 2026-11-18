#include "engine/recorders.hpp"

namespace kompartment {

const std::vector<std::string>& recorder_kinds() {
    static const std::vector<std::string> v = {"min_max", "running_mean", "snapshot", "delay", "trigger"};
    return v;
}
bool is_remembering_kind(std::string_view kind) {
    return kind == "min_max" || kind == "running_mean" || kind == "snapshot" || kind == "delay";
}
std::string recorder_collection(std::string_view kind) {
    if (kind == "min_max") return "min_maxes";
    if (kind == "running_mean") return "running_means";
    if (kind == "snapshot") return "snapshots";
    if (kind == "delay") return "delays";
    return "triggers";
}
int direction_sign(std::string_view direction) { return direction == "rising" ? 1 : direction == "falling" ? -1 : 0; }
std::vector<std::string> event_fields(std::string_view kind) {
    if (kind == "min_max" || kind == "running_mean") return {"reset_trigger", "start_trigger", "stop_trigger"};
    if (kind == "snapshot") return {"trigger"};
    return {};
}
std::vector<std::string> equation_fields(std::string_view kind) {
    if (kind == "min_max" || kind == "running_mean") return {"target"};
    if (kind == "snapshot") return {"target", "initial"};
    if (kind == "delay") return {"target", "delay"};
    return {"first", "second"};
}
RecorderAction event_action(std::string_view field) {
    if (field == "reset_trigger") return RecorderAction::Reset;
    if (field == "start_trigger") return RecorderAction::Start;
    if (field == "stop_trigger") return RecorderAction::Stop;
    return RecorderAction::Snapshot;
}

void History::add(double time, double value) {
    std::size_t n = t.size();
    if (n > 0 && time <= t.back()) {
        t.back() = time;
        v.back() = value;
        return;
    }
    if (n >= 2 && v[n - 1] == value && v[n - 2] == value) {
        t.back() = time;
        return;
    }
    t.push_back(time);
    v.push_back(value);
}

long History::below(double time) const {
    long lo = 0, hi = static_cast<long>(t.size()) - 1;
    if (hi < 0 || time < t[0]) return -1;
    while (lo < hi) {
        long mid = (lo + hi + 1) >> 1;
        if (t[static_cast<std::size_t>(mid)] <= time) lo = mid;
        else hi = mid - 1;
    }
    return lo;
}

double History::hold(double time) const {
    if (t.empty()) return 0.0;
    if (time <= t.front()) return v.front();
    if (time >= t.back()) return v.back();
    return v[static_cast<std::size_t>(below(time))];
}

double History::lerp(double time) const {
    if (t.empty()) return 0.0;
    if (time <= t.front()) return v.front();
    if (time >= t.back()) return v.back();
    std::size_t i = static_cast<std::size_t>(below(time));
    double t0 = t[i], t1 = t[i + 1];
    if (t1 == t0) return v[i + 1];
    return v[i] + ((time - t0) / (t1 - t0)) * (v[i + 1] - v[i]);
}

Recorder::Recorder(std::string_view kind_name, std::string_view operation, bool recording_)
    : kind(kind_name == "running_mean" ? RecorderKind::RunningMean
           : kind_name == "snapshot" ? RecorderKind::Snapshot
           : kind_name == "delay" ? RecorderKind::Delay
           : RecorderKind::MinMax),
      sign(operation == "min" ? -1 : 1),
      starts_recording(recording_),
      recording(recording_) {}

void Recorder::prime(double t0, double seed) {
    history.clear();
    recording = starts_recording;
    total_time = 0.0;
    last_time = t0;
    reset_sum = 0.0;
    if (kind == RecorderKind::RunningMean) {
        history.add(t0, recording ? seed : 0.0);
        return;
    }
    history.add(t0, seed);
}

void Recorder::store(double t, double current) {
    if (kind == RecorderKind::MinMax) {
        if (current != history.last_value()) history.add(t, current);
    } else if (kind == RecorderKind::Delay) {
        history.add(t, current);
    } else if (kind == RecorderKind::RunningMean) {
        if (recording) {
            history.add(t, current);
            total_time += t - last_time;
        }
        last_time = t;
    }
}

void Recorder::fire(RecorderAction what, double t, double target, double summed) {
    switch (what) {
        case RecorderAction::Snapshot: history.add(t, target); break;
        case RecorderAction::Reset:
            history.add(t, target);
            if (kind == RecorderKind::RunningMean) {
                reset_sum = summed;
                total_time = 0.0;
                last_time = t;
            }
            break;
        case RecorderAction::Start:
            recording = true;
            last_time = t;
            break;
        case RecorderAction::Stop: recording = false; break;
    }
}

double Recorder::extreme(double t, double target) const {
    if (t <= history.last_time()) return history.hold(t);
    if (!recording) return history.last_value();
    double last = history.last_value();
    if (last != last || target != target) return std::numeric_limits<double>::quiet_NaN();   // Math.max / Math.min: NaN wins
    // Python's max(a, b) and min(a, b): the first unless the second is strictly beyond it.
    return sign > 0 ? (target > last ? target : last) : (target < last ? target : last);
}

double Recorder::mean_of(double t, double summed, double target) const {
    if (t <= history.last_time()) return history.hold(t);
    double elapsed = elapsed_at(t);
    return elapsed > 0 ? (summed - reset_sum) / elapsed : target;
}

}  // namespace kompartment
