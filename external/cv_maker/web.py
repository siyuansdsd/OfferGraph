#!/usr/bin/env python3
import os
import sys

sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), "src"))

try:
    from cv_maker.env_loader import load_env_file
    load_env_file()
except ImportError:
    pass

from cv_maker.web_server import main


if __name__ == "__main__":
    main()
