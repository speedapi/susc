# SUS compiler
This repository contains the compiler for the SUS description language. Install it with:
```
pip3 install susc
```

## Usage
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