// A lock for a cache a value fills as it is read.
//
// A few values the engine reads on every run keep what they have worked out once
// (an index space's strides, a project's output times). A probabilistic run reads
// them from several threads at once, each running realisations on a system of its
// own that shares the project and the build: so the filling is done under a lock.

#pragma once

#include <mutex>

namespace kompartment {

/// A mutex a value can carry and still be copied: a copy has a lock of its own (the
/// cache it guards is copied with the value, which no other thread is filling then --
/// values are copied while a model is built, before anything runs on threads).
class CacheLock {
public:
    CacheLock() = default;
    CacheLock(const CacheLock&) noexcept {}
    CacheLock& operator=(const CacheLock&) noexcept { return *this; }

    std::mutex& get() const noexcept { return mutex_; }

private:
    mutable std::mutex mutex_;
};

}  // namespace kompartment
