"""Create a source/data Linux transfer archive, without running training."""

import argparse
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TREES = ('FAN_ATPG', 'fault_order_rl', 'fault_embedding', 'scripts', 'configs',
         'datasets', 'third_party', 'tests', 'validation', 'docs')
FILES = ('README.md', 'LINUX.md', 'requirements-fault-order.txt',
         'requirements-fault-embeddings.txt', 'pytest.ini', '.gitignore', '.gitattributes')
SKIP_DIRS = {'.git', '__pycache__', 'build', 'dist', '.pytest_cache', 'bin', 'lib',
             'fan_features', 'fan_full_features', 'verilog_features'}
SKIP_SUFFIXES = {'.pyd', '.so', '.dll', '.exe', '.o', '.a', '.d', '.pyc', '.log', '.bench'}


def include(path):
    relative = path.relative_to(ROOT)
    if relative.parts[0] == 'datasets' and (len(relative.parts) < 2 or relative.parts[1] not in ('verilog','itc99_nangate45')):
        return False
    return not (set(relative.parts[:-1]) & SKIP_DIRS or path.suffix in SKIP_SUFFIXES
                or any(part.endswith('.egg-info') for part in relative.parts[:-1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/fan-atpg-linux.tar.gz')
    args = parser.parse_args()
    paths = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    paths.extend(p for name in TREES for p in (ROOT / name).rglob('*')
                 if p.is_file() and include(p))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz', compresslevel=6) as archive:
        for path in sorted(paths):
            name = 'fan-atpg/' + path.relative_to(ROOT).as_posix()
            content = path.read_bytes()
            if path.suffix == '.sh':
                content = content.replace(b'\r\n', b'\n')
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if path.suffix == '.sh' else 0o644
            archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_name(args.output.name + '.sha256').write_text(
        digest + '  ' + args.output.name + '\n', encoding='utf-8')
    print(str(args.output.resolve()))
    print('Files:', len(paths), 'Bytes:', args.output.stat().st_size)
    print('SHA256:', digest)


if __name__ == '__main__':
    main()
