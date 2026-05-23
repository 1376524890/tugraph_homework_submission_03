#pragma once

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace lgraph_log {

enum severity_level {
    TRACE,
    DEBUG,
    INFO,
    WARNING,
    ERROR,
    FATAL
};

class NullLogger {
 public:
    template <typename T>
    NullLogger& operator<<(const T&) {
        return *this;
    }
};

class FatalLogger {
 public:
    FatalLogger(const std::string& file, int line) {
        stream_ << file << ":" << line << " ";
    }

    ~FatalLogger() noexcept(false) {
        throw std::runtime_error(stream_.str());
    }

    template <typename T>
    FatalLogger& operator<<(const T& value) {
        stream_ << value;
        return *this;
    }

 private:
    std::ostringstream stream_;
};

}  // namespace lgraph_log

#define LOG_DEBUG() ::lgraph_log::NullLogger()
#define LOG_INFO() ::lgraph_log::NullLogger()
#define LOG_WARN() ::lgraph_log::NullLogger()
#define LOG_ERROR() ::lgraph_log::NullLogger()
#define LOG_FATAL() ::lgraph_log::FatalLogger(__FILE__, __LINE__)
#define FMA_UT_LOG(LEVEL) ::lgraph_log::NullLogger()
#define AUDIT_LOG() ::lgraph_log::NullLogger()
