// UTF-8 filesystem paths for the original parser entry points.
#pragma once
#include <cstdio>
#ifdef _WIN32
#include <codecvt>
#include <locale>
inline FILE *fan_open_read(const char *path) {
  auto wide=std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>>{}.from_bytes(path);
  return _wfopen(wide.c_str(), L"r");
}
#else
inline FILE *fan_open_read(const char *path) { return fopen(path,"r"); }
#endif
