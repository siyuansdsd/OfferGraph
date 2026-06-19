#!/usr/bin/env python3
# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import os

# Ensure the current directory and src are in the path
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from cv_maker.env_loader import load_env_file
    load_env_file()
except ImportError:
    pass

try:
    from cv_maker.main import main
except ImportError as e:
    print(f"Error importing cv_maker: {e}")
    sys.exit(1)

if __name__ == "__main__":
    main()
