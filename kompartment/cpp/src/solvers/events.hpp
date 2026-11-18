// Where an event function crosses zero inside a step (engine/solvers/events.py).

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <utility>
#include <vector>

#include "solvers/types.hpp"

namespace kompartment {

/// The discrete events a solve stops at: `n` functions, `fun(out, t, y)`
/// writing their values, and the direction each counts (1 rising, -1 falling,
/// 0 either).
struct EventFunctions {
    int n = 0;
    EventFunction fun;
    std::vector<std::int8_t> direction;

    EventFunctions() = default;
    /// The directions by their sign.
    template <class Number>
    EventFunctions(int n_, EventFunction fun_, const std::vector<Number>& direction_) : n(n_), fun(std::move(fun_)) {
        direction.reserve(direction_.size());
        for (Number d : direction_) direction.push_back(static_cast<std::int8_t>(d > 0 ? 1 : (d < 0 ? -1 : 0)));
    }
};

namespace sv {

constexpr double EV_EPS = 0x1p-52;

/// `Math.sign`: NaN for NaN, the zero itself for a zero (so -0 and +0 stay
/// apart as values but compare equal).
inline double ev_sign(double v) noexcept { return v != v ? NOT_A_NUMBER : (v != 0 ? (v > 0 ? 1.0 : -1.0) : v); }

inline bool ev_crosses(const Vec& vl, const Vec& vr, const std::vector<std::int8_t>& direction, std::size_t i) noexcept {
    const double a = vl[i];
    const double b = vr[i];
    const double sa = ev_sign(a);
    const double sb = ev_sign(b);
    if (sa == sb) return false;
    return static_cast<double>(direction[i]) * (b - a) >= 0;
}

inline bool ev_any_crossing(const Vec& vl, const Vec& vr, const std::vector<std::int8_t>& direction) noexcept {
    for (std::size_t i = 0; i < vl.size(); i++)
        if (ev_crosses(vl, vr, direction, i)) return true;
    return false;
}

inline double ev_crossing_tolerance(double tl, double tr) noexcept {
    const double scale = py_max(py_max(std::fabs(tl), std::fabs(tr)), 1.0);
    return py_min(std::fabs(tr - tl), (64 * EV_EPS) * scale);
}

inline double ev_earliest_secant(const Vec& vlo, const Vec& vhi, const std::vector<std::int8_t>& direction) noexcept {
    double frac = 1.0;
    for (std::size_t i = 0; i < vlo.size(); i++) {
        if (!ev_crosses(vlo, vhi, direction, i)) continue;
        const double a = vlo[i];
        const double b = vhi[i];
        double f = a == b ? 0.5 : -a / (b - a);
        if (!(0 < f && f < 1)) f = 0.5;
        if (f < frac) frac = f;
    }
    return frac;
}

/// What locating a crossing needs, made once for a solve, and what it found:
/// the time, the event functions' values there (the caller's `vr`, or one of
/// the buffers here) and the events that cross (counted from zero).
struct EventWork {
    Vec scratch[3];
    double t = 0.0;
    const Vec* values = nullptr;
    std::vector<int> which;

    EventWork() = default;
    explicit EventWork(int n) {
        for (Vec& b : scratch) b.assign(static_cast<std::size_t>(n), 0.0);
        which.reserve(static_cast<std::size_t>(n));
    }
};

/// The first crossing in (tl, tr]: true with `w.t`, `w.values` and `w.which`
/// set, or false. `values_at(out, t)` writes the event functions' values at `t`
/// (read from the step's interpolant).
template <class F>
bool ev_first_crossing(EventWork& w, F&& values_at, double tl, const Vec& vl, double tr, const Vec& vr,
                       const std::vector<std::int8_t>& direction, double t_start) {
    const std::size_t n = vl.size();
    const double tol = ev_crossing_tolerance(tl, tr);
    const double tdir = tr != tl ? std::copysign(1.0, tr - tl) : 0.0;
    double lo = tl;
    const Vec* vlo = &vl;
    if (tl == t_start) {
        bool resting = false;
        for (std::size_t i = 0; i < n; i++) {
            if (vl[i] == 0 && vr[i] != 0) {
                resting = true;
                break;
            }
        }
        if (resting) {
            lo = tl + (tdir * 0.5) * tol;
            if (tdir * (tr - lo) <= 0) return false;
            Vec& first = w.scratch[0];
            std::fill(first.begin(), first.end(), 0.0);
            values_at(first, lo);
            for (std::size_t i = 0; i < n; i++)
                if (first[i] == 0 && vl[i] == 0) first[i] = vr[i];
            vlo = &first;
        }
    }
    if (!ev_any_crossing(*vlo, vr, direction)) return false;
    double hi = tr;
    const Vec* vhi = &vr;
    int kept = 0;
    int same_end = 0;
    for (int round = 0; round < 80; round++) {
        if (!(std::fabs(hi - lo) > tol)) break;
        double mid;
        if (same_end >= 2) {
            mid = 0.5 * (lo + hi);
        } else {
            mid = lo + ev_earliest_secant(*vlo, *vhi, direction) * (hi - lo);
            const double inner = 0.5 * tol;
            if (tdir * (mid - lo) < inner) mid = lo + tdir * inner;
            if (tdir * (hi - mid) < inner) mid = hi - tdir * inner;
            if (!(tdir * (mid - lo) > 0 && tdir * (hi - mid) > 0)) mid = 0.5 * (lo + hi);
        }
        // The values at the middle go into the one buffer neither end reads.
        Vec* vmid = &w.scratch[0];
        if (vmid == vlo || vmid == vhi) vmid = &w.scratch[1];
        if (vmid == vlo || vmid == vhi) vmid = &w.scratch[2];
        std::fill(vmid->begin(), vmid->end(), 0.0);
        values_at(*vmid, mid);
        if (ev_any_crossing(*vlo, *vmid, direction)) {
            hi = mid;
            vhi = vmid;
            same_end = kept == 1 ? same_end + 1 : 1;
            kept = 1;
        } else {
            lo = mid;
            vlo = vmid;
            same_end = kept == -1 ? same_end + 1 : 1;
            kept = -1;
        }
    }
    w.which.clear();
    for (std::size_t i = 0; i < n; i++)
        if (ev_crosses(*vlo, *vhi, direction, i)) w.which.push_back(static_cast<int>(i));
    w.t = hi;
    w.values = vhi;
    return true;
}

/// Reads the event functions at the end of a step (into `vr`) and, if any
/// crossed, finds the first crossing inside it (`locate_crossing`).
/// `dense_at(out, t)` writes the state at `t` inside the step; `ybuf` is
/// room for it.
template <class D>
bool ev_locate_crossing(const EventFunctions& ev, EventWork& w, double t, const Vec& vl, double tnew, const Vec& ynew,
                        Vec& vr, D&& dense_at, Vec& ybuf, double t_start) {
    ev.fun(vr, tnew, ynew);
    if (!ev_any_crossing(vl, vr, ev.direction)) return false;
    auto at = [&](Vec& out, double tq) {
        dense_at(ybuf, tq);
        ev.fun(out, tq, ybuf);
    };
    return ev_first_crossing(w, at, t, vl, tnew, vr, ev.direction, t_start);
}

}  // namespace sv

}  // namespace kompartment
