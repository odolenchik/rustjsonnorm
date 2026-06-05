# Roadmap

## Planned Features

### Preserve original types (numbers, booleans)
Currently all values are converted to strings. Add a `preserve_types` option so that numbers remain as numeric Python types and booleans stay as booleans. This is the default behavior users expect from `json_normalize`.

### Optimize normalize_many bytes path — avoid double copy
The current `normalize_many` implementation copies each byte slice into an owned `Vec<u8>` before passing to rayon, resulting in a double-copy (once for the Vec, once inside `process_one`). We could accept `&[u8]` directly from PyBytes and eliminate the intermediate allocation. This requires managing lifetimes carefully since rayon closures need `'static` bounds — potentially via thread-local storage or by collecting into an arena-style buffer before dispatching to rayon.
