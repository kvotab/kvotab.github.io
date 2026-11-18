#include "solvers/solvers.hpp"

#include <utility>

namespace kompartment {

SolverError::SolverError(std::string kind_, std::string message_, double t_)
    : kind(std::move(kind_)),
      message(std::move(message_)),
      t(t_),
      trace(Json::array()),
      last_t(std::numeric_limits<double>::quiet_NaN()),
      stats(Json::object()) {}

Vec& take_row(RowPool& pool, const Vec& y) {
    const std::size_t k = pool.next;
    pool.next = k + 1;
    if (k >= pool.rows.size()) {
        pool.rows.push_back(std::make_unique<Vec>(y));
    } else {
        *pool.rows[k] = y;          // the row's own memory, where it is long enough
    }
    return *pool.rows[k];
}

Rows::Rows(const Rows& other) {
    rows_.reserve(other.rows_.size());
    own_.reserve(other.rows_.size());
    for (const Vec* row : other.rows_) push_copy(*row);
}

Rows& Rows::operator=(const Rows& other) {
    if (this != &other) {
        Rows copy(other);
        *this = std::move(copy);
    }
    return *this;
}

void Rows::push_copy(const Vec& y) {
    own_.push_back(std::make_unique<Vec>(y));
    rows_.push_back(own_.back().get());
}

}  // namespace kompartment
