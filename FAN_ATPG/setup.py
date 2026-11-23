"""Build the original FAN Verilog/MDT frontend and target solver.

Release archives include generated Flex/Bison snapshots. Set FAN_REGENERATE_PARSERS=1
with flex and bison on PATH to reproduce them from the original .l/.y sources.
"""
from pathlib import Path
import os
import shutil
import subprocess
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
GENERATED = ROOT / "python" / "generated"
INTERFACE = ROOT / "pkg" / "interface" / "src"
PARSERS = ("mdt_file", "vlog_file")

def generate_parsers():
    if os.environ.get("FAN_REGENERATE_PARSERS") != "1":
        return
    for tool in ("flex", "bison"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is required to regenerate original FAN parsers")
    GENERATED.mkdir(parents=True, exist_ok=True)
    for stem in PARSERS:
        subprocess.run(["bison", "-d", "-p", stem, "-o", str(Path("python/generated") / (stem + ".tab.cpp")), str(Path("pkg/interface/src") / (stem + ".y"))], check=True)
        subprocess.run(["flex", "-P" + stem, "-o" + str(Path("python/generated") / (stem + ".yy.cpp")), str(Path("pkg/interface/src") / (stem + ".l"))], check=True)

class BuildExt(build_ext):
    def build_extensions(self):
        generate_parsers()
        for extension in self.extensions:
            extension.extra_compile_args = ["/std:c++14", "/EHsc", "/O2", "/utf-8"] if self.compiler.compiler_type == "msvc" else ["-std=c++14", "-O3"]
        super().build_extensions()

sources = ["python/bindings.cpp"]
sources += ["pkg/core/src/" + stem + ".cpp" for stem in ("atpg", "simulator", "fault", "logic", "circuit")]
sources += ["pkg/interface/src/" + stem + ".cpp" for stem in ("cell", "primitive", "techlib", "netlist", "techlib_builder", "netlist_builder", "mdt_file", "vlog_file")]
sources += ["python/generated/" + stem + suffix for stem in PARSERS for suffix in (".tab.cpp", ".yy.cpp")]
setup(name="cpp-fan", version="0.2.0", ext_modules=[Extension("cpp_fan", sources,
    include_dirs=[str(ROOT/"pkg/core/src"), str(INTERFACE), str(GENERATED), str(ROOT/"include"), str(ROOT/"python/vendor/pybind11/include")],
    define_macros=[("YY_NO_UNISTD_H", "1"), ("YY_NEVER_INTERACTIVE", "1")], language="c++")], cmdclass={"build_ext": BuildExt})
