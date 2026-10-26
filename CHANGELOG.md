# Changelog

## 0.2.0 — PREDATOR package and MCP facade

- Rename the installable distribution and public Python facade to `predator`; retain `clan_subnet_detector` and the versioned identifiers `ztge.audit.v1` / `ztge.envelope.v1`.
- New report bodies identify `engine.name` as `predator`. This changes the canonical report payload and thus its content hash; historical report bytes and signatures remain verifiable as originally issued.
- Add the optional official Python MCP SDK and keep the HTTP API available as `predator-api`.
- Ship YAML contracts as package resources for status calls from wheels.
- Fix CLI `--sign-hmac` serialization and add MCP and negative-signature regression tests.
