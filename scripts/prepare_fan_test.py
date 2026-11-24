"""Discover and optionally prepare arbitrary compatible test netlists."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fault_order_rl.testing import (DEFAULT_TEST_DIR,DEFAULT_LIBRARY,DEFAULT_TEST_MANIFEST,
                                   discover_test_manifest,prepare_test_features)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-dir',type=Path,default=DEFAULT_TEST_DIR)
    parser.add_argument('--library',type=Path,default=DEFAULT_LIBRARY)
    parser.add_argument('--output',type=Path,default=DEFAULT_TEST_MANIFEST)
    parser.add_argument('--manifest-only',action='store_true')
    parser.add_argument('--device',default='auto')
    parser.add_argument('--threads',type=int)
    args=parser.parse_args()
    manifest=discover_test_manifest(args.test_dir,args.library,args.output)
    print('Discovered test netlists: '+str(manifest),flush=True)
    if not args.manifest_only:
        from fault_order_rl.runtime import configure_runtime
        configure_runtime(args.device,args.threads)
        prepare_test_features(manifest,device=args.device,threads=args.threads)

if __name__=='__main__':main()
