# Roadmap

## Planned Features

### Preserve original types (numbers, booleans)
Currently all values are converted to strings. Add a `preserve_types` option so that numbers remain as numeric Python types and booleans stay as booleans. This is the default behavior users expect from `json_normalize`.

### Accept bytes input
Add support for reading JSON directly from `bytes` (not just `str`). This avoids redundant string decoding when working with binary data sources such as network sockets or file objects opened in binary mode.
