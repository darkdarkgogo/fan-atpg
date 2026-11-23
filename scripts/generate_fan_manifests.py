"""Create Verilog/MDT FAN manifests without reading or converting BENCH."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def relative(path, base):
    return os.path.relpath(str(path.resolve()), str(base.resolve())).replace('\\', '/')


def generate(train_dir, validation_dir, output_dir, features_dir, module_dir, library_path, suffix=''):
    library_path = library_path.resolve()
    if not library_path.is_file():
        raise ValueError('Technology library does not exist: ' + str(library_path))
    sources = {split: sorted(p for p in directory.resolve().iterdir() if p.is_file() and p.suffix.lower() in ('.v', '.sv'))
               for split, directory in (('train', train_dir), ('validation', validation_dir))}
    if any(not paths for paths in sources.values()):
        raise ValueError('Both source directories must contain gate-level Verilog .v/.sv files')
    hashes = {split: {hashlib.sha256(p.read_bytes()).hexdigest() for p in paths} for split, paths in sources.items()}
    if hashes['train'] & hashes['validation']:
        raise ValueError('Train and validation contain identical Verilog content')
    if {p.stem for p in sources['train']} & {p.stem for p in sources['validation']}:
        raise ValueError('Train and validation circuit names overlap')
    if any(len({p.stem for p in paths}) != len(paths) for paths in sources.values()):
        raise ValueError('Duplicate Verilog circuit names')
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {s: output_dir / ('fan_' + s + suffix + '.json') for s in sources}
    if any(p.exists() for p in outputs.values()):
        raise ValueError('Manifest already exists; use a new output directory or suffix')
    for split, paths in sources.items():
        entries = []
        for path in paths:
            prefix = features_dir / split / path.stem / path.stem
            entries.append({'name': path.stem, 'netlist': relative(path, output_dir), 'library': relative(library_path, output_dir),
                'graph': relative(Path(str(prefix) + '.graph.json'), output_dir),
                'embeddings': relative(Path(str(prefix) + '.fault_embeddings.npz'), output_dir),
                'metadata': relative(Path(str(prefix) + '.faults.json'), output_dir)})
        content = {'version': 2, 'backend': 'FAN', 'input_format': 'verilog',
                   'cpp_fan_dir': relative(module_dir, output_dir), 'circuits': entries}
        outputs[split].write_text(json.dumps(content, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(str(outputs[split].resolve()) + ': ' + str(len(entries)) + ' Verilog circuits')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-dir', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True, help='FAN-compatible MDT technology library')
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--features-dir', type=Path, default=ROOT / 'datasets/verilog_features')
    parser.add_argument('--module-dir', type=Path, default=ROOT / 'FAN_ATPG')
    args = parser.parse_args()
    generate(args.train_dir, args.validation_dir, args.out_dir, args.features_dir, args.module_dir, args.library)


if __name__ == '__main__':
    main()
