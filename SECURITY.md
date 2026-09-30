# Security

The bridge listens only on `127.0.0.1`, rejects requests carrying an `Origin` header and
can require `SIGIL_BRIDGE_TOKEN`. It never exposes binary resources and only writes an
existing textual manifest item after its SHA-256 hash is confirmed.

Do not expose port 8765 through port forwarding or a public proxy. Report vulnerabilities
privately to the repository owner instead of opening a public issue.
