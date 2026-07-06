# Security checklist

- No secrets, tokens, or credentials committed in the diff.
- User-controlled input must be validated/escaped before use in SQL, shell
  commands, file paths, or HTML (injection risks).
- New HTTP endpoints must have an explicit authentication/authorization
  story — flag any that appear unauthenticated.
- Avoid `eval`/dynamic code execution on non-constant input.
- Crypto: no home-rolled algorithms, no MD5/SHA1 for security purposes.
