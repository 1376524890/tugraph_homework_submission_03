#pragma once

namespace boost {
namespace algorithm {

template <typename InputIt, typename OutputIt>
OutputIt hex(InputIt first, InputIt last, OutputIt out) {
    static const char* digits = "0123456789ABCDEF";
    for (; first != last; ++first) {
        unsigned char c = static_cast<unsigned char>(*first);
        *out++ = digits[(c >> 4) & 0x0F];
        *out++ = digits[c & 0x0F];
    }
    return out;
}

}  // namespace algorithm
}  // namespace boost
