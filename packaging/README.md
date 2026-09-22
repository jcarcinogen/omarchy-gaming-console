# Engine helper package

This package is the privilege boundary for Omarchy Gaming Console. It must be built only after the plugin commit intended for marketplace review exists remotely.

## Reproducible build

On an Arch/Omarchy builder, copy this `packaging/` directory without modification and run:

```bash
export REVIEWED_COMMIT=<exact-40-character-marketplace-commit>
makepkg --cleanbuild
```

`prepare()` fails unless the value is exactly 40 lowercase hexadecimal characters, GitHub serves that exact object from the fixed repository, and the fetched object resolves to the same commit. The resulting package records the value in both the installed helper and `/usr/share/omarchy-gaming-console/reviewed-commit`.

Rename the built package to the stable release-asset name before signing:

```bash
mv omarchy-gaming-console-engine-*.pkg.tar.zst omarchy-gaming-console-engine-any.pkg.tar.zst
gpg --local-user 5F080326EB4583CA063F9CA56E6DF2952E09D28D \
  --detach-sign omarchy-gaming-console-engine-any.pkg.tar.zst
```

Upload the package, detached signature, and the exported public key as assets on the engine-helper release. Never upload the private key or its passphrase. Verify the package file list, embedded commit, and signature before publishing.
