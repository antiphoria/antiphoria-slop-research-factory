## Install

Other repo pulls SDK as Git dep (no PyPI yet):

```toml
[project]
dependencies = [
  "antiphoria-slop-provenance @ git+https://github.com/antiphoria/antiphoria-slop-provenance@local-sdk",
]
```

Or vendored path:

```toml
"antiphoria-slop-provenance @ file:///path/to/antiphoria-slop-provenance"
```

Hard transitive deps that other repo gets: `cryptography`, `liboqs-python`, `pydantic>=2`, `rfc8785`, `filelock`. Native liboqs must be on host.

## Import surface

One package, flat:

```python
from antiphoria_sdk import (
    SealEngine, StepType, verify_chain,
    HybridSigner, HybridVerifier, HybridKeys,
    generate_ephemeral_keys, load_keys_from_env,
    ChainRecord, SealReceipt, VerificationReport,
    ChainError, ChainSequenceError,
)
```

## Producer flow (factory writes chain)

```python
keys = load_keys_from_env()  # env: ANTIPHORIA_*_B64
signer = HybridSigner(keys)
verifier = HybridVerifier({keys.fingerprint: keys})

engine = SealEngine.create(
    workspace=Path("runs/run-2026-04-29"),
    run_id="run-2026-04-29",
    signer=signer,
    verifier=verifier,
)

await engine.begin_chain(research_brief={"title": "..."})

await engine.seal(
    step_type=StepType.PRE_GENERATOR,
    content_file_paths=["steps/0001_pre_generator/intent.json"],
    metadata={"prompt_hash": "...", "model": "..."},
)
# ... more seals ...

report = await engine.verify_chain()
assert report.chain_intact, report.summary()
```

Resume after crash:

```python
engine = SealEngine.resume(workspace, run_id, signer=signer, verifier=verifier)
# verifies whole chain, restores latest_step + latest_hash
```

## Consumer flow (auditor verifies chain, no signer)

```python
verifier = HybridVerifier({fingerprint: HybridKeys.public_only_from_bytes(...)})
report = await verify_chain(workspace, run_id, verifier=verifier)
if not report.chain_intact:
    print(f"BROKEN at step {report.first_error_index}")
    for s in report.steps:
        if s.errors:
            print(s.record_path, s.errors)
```

`verify_chain` no signer needed → uses internal `_VerifyOnlySigner`.

## Bridge to existing CLI keys (your case)

Other repo (or `src/runtime/sdk_bridge.py` here) wraps existing `crypto_notary` PEMs into `HybridKeys`:

```python
# bridge_signer.py in factory repo
from antiphoria_sdk import HybridKeys, HybridSigner, Signature

def load_hybrid_keys_from_pems(mldsa_priv_path, mldsa_pub_path,
                               ed_priv_pem, ed_pub_pem) -> HybridKeys:
    return HybridKeys(
        mldsa_public=Path(mldsa_pub_path).read_bytes(),
        ed25519_public=_raw_ed25519_pub_from_pem(ed_pub_pem),
        mldsa_private=Path(mldsa_priv_path).read_bytes(),
        ed25519_private=_raw_ed25519_priv_from_pem(ed_priv_pem),
    )
```

Then `HybridSigner(keys)` plugs into `SealEngine`. SDK enforces `signature.public_key_fingerprint == signer.public_key_fingerprint` so bridge must keep consistency.

## Threat boundary other repo must respect

- **One engine per `(workspace, run_id)`**. Don't share across asyncio tasks.
- **Cross-process**: filelock protects writes from corruption, but each engine's in-memory `latest_hash` goes stale if peer writes. Recover via `SealEngine.resume(...)`.
- **Content paths**: only POSIX-safe relative under workspace. Absolute outside workspace → `ChainError`. No `..` traversal in record keys (validator).
- **Reserved metadata key**: `research_brief` at GENESIS. Don't put in regular `metadata` if also passing `research_brief=`.
- **Chain file format**: `<workspace>/chain/000NNN_STEP_TYPE.json`. Caller never writes there directly. Lock file `<workspace>/chain/.chain.lock`.

## Doc reference

`docs/bridging-existing-lib.md` covers env vars, perf note (fresh `oqs.Signature` per verify), fingerprint binding contract, cross-process recovery.

# Bridging antiphoria_sdk to the existing slop CLI keys

The `antiphoria_sdk` package is intentionally **not** coupled to `src.adapters` or
`src.services`. Your factory or a thin integration layer can still reuse the
**same cryptographic material** as
`src/adapters/crypto_notary.py` by adapting bytes into `antiphoria_sdk.signing.HybridKeys` and passing `antiphoria_sdk.signing.HybridSigner` to `antiphoria_sdk.chain.SealEngine`.

## What matches today

- **ML-DSA**: The SDK uses **ML-DSA-44** and the same `import oqs` / algorithm
  string as the notary.
- **Ed25519**: The SDK uses **raw 32-byte** Ed25519 private/public keys
  (`cryptography` raw encoding), compatible with keys exported in that form.

## What differs

- **Artifact format**: Markdown provenance artifacts signed by the CLI use a
  different message domain than SDK `ChainRecord` JSON. They are separate
  chains of trust unless you explicitly define a cross-link in metadata.
- **Fingerprint**: SDK `HybridKeys.fingerprint` is a **synthetic** SHA-256 over
  `mldsa_public || ed25519_public`, truncated to 32 hex characters. The CLI
  may expose a different signer fingerprint string for ML-DSA / Ed25519 PEM
  registration; compare documents carefully before treating them as
  interchangeable identifiers.
- **Fingerprint binding**: `SealEngine` enforces that the fingerprint embedded
  in each `Signature` matches `signer.public_key_fingerprint`. A custom
  adapter MUST return a `Signature` whose `public_key_fingerprint` equals the
  value its `Signer.public_key_fingerprint` attribute advertises, or
  `_build_sign_and_write` raises `ChainError` before the record reaches disk.

## Performance characteristics

`HybridVerifier.verify` instantiates a fresh `oqs.Signature` context per
call. This is correct but not free: liboqs setup involves a significant
malloc/init pass. If you bridge this into a hot path (e.g. verifying long
chains repeatedly), reuse one `SealEngine` for multiple `verify_chain`
calls or cache verifiers per fingerprint at the adapter layer.

## Suggested adapter shape (pseudo-code)

Implement `antiphoria_sdk.signing.Signer` with:

- `public_key_fingerprint`: return a `HybridKeys(...).public_only().fingerprint`
  after you assemble `HybridKeys` from your PEM or env-loaded bytes. This
  attribute is read by `SealEngine` for fingerprint binding (see above).
- `sign(data: bytes) -> antiphoria_sdk.Signature`: delegate to `HybridSigner(keys).sign(data)`.

Do **not** import `src.adapters.crypto_notary` from inside `antiphoria_sdk`.
Keep the adapter in your factory repo or an optional `src/runtime/sdk_bridge.py`
in this repo if you choose to add it later.

## Environment loader

`antiphoria_sdk.load_keys_from_env()` expects base64-encoded **raw** key bytes
under:

- `ANTIPHORIA_MLDSA_PRIVATE_KEY_B64` / `ANTIPHORIA_MLDSA_PUBLIC_KEY_B64`
- `ANTIPHORIA_ED25519_PRIVATE_KEY_B64` / `ANTIPHORIA_ED25519_PUBLIC_KEY_B64`

These names are **SDK-specific** and differ from `PQC_PRIVATE_KEY_PATH` and
`ED25519_PRIVATE_KEY_PATH` used by the CLI. A bridge layer should map one
configuration story to the other without merging the modules.

## Cross-process safety

`SealEngine` acquires a `filelock.FileLock` on `<workspace>/chain/.chain.lock`
while writing each record. Two adapters/processes pointed at the same
workspace will not corrupt the chain on disk, but each engine's in-memory
`latest_step` / `latest_hash` may go stale after a peer write. To recover,
construct a new engine via `SealEngine.resume(...)`, which re-validates the
chain and rebuilds in-memory state from disk.
