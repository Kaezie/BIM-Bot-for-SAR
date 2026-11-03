# Verification evidence

The JSON files in this directory record software checks, short live functional
checks and unresolved failures. Each report's scope and limitations apply;
software checks do not establish physical acceptance or measured model accuracy.

For the October 30 review, see
[review readiness](review_readiness_2026-10-30.json) and
[the groupmate handoff](../REVIEW_HANDOFF.md).

Seventeen large raw diagnostic traces remain on the operator's machine and are
ignored by Git. Their filenames, byte counts and SHA-256 checksums are recorded
in [the local capture index](local_capture_index_2026-10-30.json). Some historical
notes and summary reports refer to these raw sources; those captures are not
present in a fresh checkout. The relevant concise result reports remain shared.
The index preserves the identity of the local evidence without adding more than
10 MB of repetitive capture data to the review. No capture was deleted or altered.

Private environment files, credential headers, firmware backup binaries, raw
supplied sketches, recordings and runtime/session data remain outside this
directory and outside version control.
