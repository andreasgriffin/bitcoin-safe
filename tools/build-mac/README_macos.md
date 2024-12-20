# Running Bitcoin_Safe from source on macOS (development version)

## Prerequisites

- [brew](https://brew.sh/)
- python3
- git

## Main steps

### 1. Check out the code from GitHub:
```
$ git clone https://github.com/andreasgriffin/bitcoin-safe.git
$ cd bitcoin_safe
$ git submodule update --init
```

### 2. Prepare for compiling libsecp256k1

To be able to build the `bitcoin_safe-ecc` package from source
(which is pulled in when installing Bitcoin_Safe in the next step),
you need:
```
$ brew install autoconf automake libtool coreutils
```

### 3. Install Bitcoin_Safe

Run install (this should install the dependencies):
```
$ python3 -m pip install --user -e ".[gui,crypto]"
```

### 4. Run bitcoin_safe:
```
$ ./run_bitcoin_safe
```
