"""Import gate-level Verilog plus an MDT library and create FAN manifests."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.generate_fan_manifests import generate


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_checked(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(source) != digest(destination):
            raise ValueError('Existing file differs: ' + str(destination))
    else:
        shutil.copyfile(str(source), str(destination))
    if digest(source) != digest(destination):
        raise ValueError('Copy checksum mismatch: ' + str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-dir', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--destination-root', type=Path, default=ROOT)
    args = parser.parse_args()
    destination = args.destination_root.resolve()
    library = args.library.resolve()
    if not library.is_file():
        raise ValueError('Missing MDT library: ' + str(library))
    copied_library = destination / 'datasets/verilog/imported_library' / library.name
    copy_checked(library, copied_library)
    rows = []
    for split, directory in (('train', args.train_dir), ('validation', args.validation_dir)):
        files = sorted(p for p in directory.resolve().iterdir() if p.is_file() and p.suffix.lower() in ('.v', '.sv'))
        if not files:
            raise ValueError('No gate-level Verilog inputs: ' + str(directory))
        for source in files:
            target = destination / 'datasets/verilog' / ('imported_' + split) / source.name
            copy_checked(source, target)
            rows.append({'split': split, 'source': str(source), 'netlist': str(target.relative_to(destination)), 'sha256': digest(target)})
    generate(destination / 'datasets/verilog/imported_train', destination / 'datasets/verilog/imported_validation',
             destination / 'configs', destination / 'datasets/verilog_features', destination / 'FAN_ATPG', copied_library, suffix='_imported')
    (destination / 'datasets/verilog/imported_provenance.json').write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
