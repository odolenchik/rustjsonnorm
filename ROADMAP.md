# Roadmap

## Planned Features

### Preserve original types (numbers, booleans)
Currently all values are converted to strings. Add a `preserve_types` option so that numbers remain as numeric Python types and booleans stay as booleans. This is the default behavior users expect from `json_normalize`.
