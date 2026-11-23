"""Compatibility entry point: check arbitrary test-directory inputs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from validation.check_test_inputs import main
if __name__=='__main__': main()
