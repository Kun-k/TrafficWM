#include <sstream>
#include <stdexcept>
#include <string>

namespace c10::detail {

[[noreturn]] void torchCheckFail(
    const char* function,
    const char* file,
    unsigned int line,
    const std::string& message) {
  std::ostringstream detail;
  detail << "PyTorch check failed at " << file << ':' << line << " in " << function;
  if (!message.empty()) {
    detail << ": " << message;
  }
  throw std::runtime_error(detail.str());
}

[[noreturn]] void torchInternalAssertFail(
    const char* function,
    const char* file,
    unsigned int line,
    const char* condition,
    const std::string& message) {
  std::ostringstream detail;
  detail << "PyTorch assertion failed: " << condition << " at " << file << ':' << line
         << " in " << function;
  if (!message.empty()) {
    detail << ": " << message;
  }
  throw std::runtime_error(detail.str());
}

}  // namespace c10::detail
