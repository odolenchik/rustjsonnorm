# Roadmap

## Planned Features

### Preserve original types (numbers, booleans)
Currently all values are converted to strings. Add a `preserve_types` option so that numbers remain as numeric Python types and booleans stay as booleans. This is the default behavior users expect from `json_normalize`.

### Accept bytes input
Add support for reading JSON directly from `bytes` (not just `str`). This avoids redundant string decoding when working with binary data sources such as network sockets or file objects opened in binary mode.

### Configurable error handling in stream_ndjson
Currently malformed lines are silently skipped. Add an option (`skip_errors=True` by default for backwards compatibility, configurable to raise) that raises a Python exception with the line number and content when parsing fails.
