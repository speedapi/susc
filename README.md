<p align="center"><img src="https://github.com/amogus-api/info/raw/master/logos/logo_color_on_white.png" height="128"/></p>

![Sus level](https://img.shields.io/badge/sus%20level-150%25-red)
![License](https://img.shields.io/github/license/amogus-api/susc)
![Version](https://img.shields.io/pypi/v/susc)
![Downloads](https://img.shields.io/pypi/dm/susc)
![PRs and issues](https://img.shields.io/badge/PRs%20and%20issues-welcome-brightgreen)

# SUS compiler
This repository contains the compiler for the SUS description language. Install it with:
```
pip3 install susc
```

# Usage
```
susc --help
# OR
python3 -m susc --help
```

## Usage (`.ts` file generation)
```
susc --gen-ts [file]
```
This command will make susc watch `[file]` and its dependencies and generate `.ts` for the root one. Extremely useful in combination with `webpack` and `sus-loader`.\
**NOTE**: consider adding this file to your VCS ignore list (e.g. `.gitignore`)