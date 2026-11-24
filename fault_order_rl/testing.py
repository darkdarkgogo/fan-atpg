"""Discover an open test directory without binding it to training checkpoints."""
import json
import hashlib
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_TEST_DIR=ROOT/'FAN_ATPG/netlist/test'
DEFAULT_LIBRARY=ROOT/'FAN_ATPG/techlib/mod_nangate45.mdt'
DEFAULT_TEST_MANIFEST=ROOT/'configs/fan_test.json'

def discover_test_manifest(directory=DEFAULT_TEST_DIR, library=DEFAULT_LIBRARY,
                           output=DEFAULT_TEST_MANIFEST, features=None, module_dir=None):
    directory,library,output=map(lambda p:Path(p).resolve(),(directory,library,output))
    if not library.is_file(): raise ValueError('Missing test MDT library: '+str(library))
    files=sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ('.v','.sv'))
    if not files: raise ValueError('Test directory contains no .v/.sv netlists: '+str(directory))
    if len({p.stem.casefold() for p in files})!=len(files): raise ValueError('Duplicate test circuit stems')
    features=Path(features or ROOT/'datasets/verilog_features/test').resolve()
    module_dir=Path(module_dir or ROOT/'FAN_ATPG').resolve()
    def rel(p):
        try:
            return os.path.relpath(str(p),str(output.parent)).replace('\\','/')
        except ValueError:
            # Windows paths on separate drives have no relative spelling.
            return Path(p).as_posix()
    entries=[]
    namespace=hashlib.sha256((str(directory)+'\n'+str(library)).encode('utf-8')).hexdigest()[:16]
    library_bytes=library.read_bytes()
    for path in files:
        revision=hashlib.sha256(path.read_bytes()+library_bytes).hexdigest()[:16]
        prefix=features/namespace/path.stem/revision/path.stem
        entries.append(dict(name=path.stem,netlist=rel(path),library=rel(library),
            graph=rel(Path(str(prefix)+'.graph.json')),
            embeddings=rel(Path(str(prefix)+'.fault_embeddings.npz')),
            metadata=rel(Path(str(prefix)+'.faults.json'))))
    value=dict(version=2,backend='FAN',input_format='verilog',cpp_fan_dir=rel(module_dir),circuits=entries)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    return output

def prepare_test_features(manifest, device="auto", threads=None):
    from .data import load_manifest,load_circuit_data
    from .environment import load_cpp_fan
    from scripts.prepare_fan_data import export
    manifest=load_manifest(manifest)
    native=load_cpp_fan(manifest.module_dir)
    for spec in manifest.circuits:
        path,library=str(spec.netlist_path),str(spec.library_path)
        graph=native.circuit_graph(path,library)
        catalog=native.catalog_stuck_at(path,library)
        export(spec,catalog,graph,device=device,threads=threads)
        load_circuit_data(spec,catalog,graph)
