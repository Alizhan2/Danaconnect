# Private Vercel Blob adapter

This document describes source behavior and operator configuration. It does not
assert that a live store, file upload or download has been verified.

## Configuration

Set `STORAGE_PROVIDER=blob`, `BLOB_STORE_ID` and `BLOB_READ_WRITE_TOKEN` on the API.
The store must be created with **private** access. Connect production separately
from preview/development; keep the read-write token server-side and outside Git.

`BLOB_STORE_ID` accepts either CLI `store_<id>` or hostname `<id>`. The application
strips `store_`, normalizes the identifier to lowercase, and checks that it matches
the identifier embedded in the static `vercel_blob_rw_<id>_<secret>` credential.
No URL or arbitrary host is accepted as a store ID. Case differences are ignored
only for the store identifier, never for the secret or attachment key.

The adapter deliberately uses the existing pinned `httpx` dependency. It does
not introduce the Vercel Python SDK and its additional dependencies, or assume
that TypeScript SDK OIDC behavior is implemented by the Python SDK. The REST wire
protocol is based on the official Python SDK: control-plane API version **11**,
`PUT https://vercel.com/api/blob?pathname=...` with
`x-vercel-blob-access: private`, and `POST /api/blob/delete` with `urls`.

## File lifecycle

- Uploads use the existing validated MIME/signature policy and size ceiling.
  Keys remain `attachments/<32 lowercase hex characters>`; random suffixes and
  overwrite are disabled. Only an exact pathname and the configured private host
  are accepted in the upload receipt. Blob URLs are never returned to clients.
- Downloads go to the canonical
  `https://<id>.private.blob.vercel-storage.com/<key>` with the server token.
  HTTP redirects and environment proxy configuration are disabled. Responses are
  streamed with bounded memory, a 20-second network timeout, identity encoding,
  and a maximum of the recorded size plus one byte. The existing download route
  requires project access, validates exact length and SHA256, and returns
  `Cache-Control: private, no-store`, `nosniff` and sandbox headers.
- Deletes use the fixed control-plane host and the same validated canonical URL.
  No automatic write retry is performed after an ambiguous network failure.
  An interrupted upload may require an operator to remove an orphan object.
- Errors contain fixed application codes. Provider bodies, URLs and tokens are
  not included in HTTP errors, audit details or attachment metadata.

S3 and local development storage are retained. The database already stores a
provider string and opaque key, so the Blob provider requires no schema change.
Changing provider does not move existing files; retain credentials for existing
records until their files are explicitly migrated or removed.

`storage_ready()` and deployment validation check credential structure only.
They cannot prove store access mode, live permissions, quota or availability.

## Hobby capacity

Current included Blob usage: 1 GB-month storage, 10,000 simple operations,
2,000 advanced operations and 10 GB Blob transfer per month. Creating a store
uses one advanced operation; deleting a store or blob is free. Private downloads
through Functions also consume the corresponding Function transfer resources.
Exceeding Hobby limits can suspend Blob access for the period documented by
Vercel; the offline readiness check does not detect that state.

The existing application limits each project to 100 files and 100 MiB. Those
per-project limits do not enforce the account's shared Blob quota.

## Sources

- [Private storage and authenticated downloads](https://vercel.com/docs/vercel-blob/private-storage)
- [Current pricing and limits](https://vercel.com/docs/vercel-blob/usage-and-pricing)
- [Official Python SDK request protocol](https://github.com/vercel/vercel-py/blob/main/src/vercel/_internal/blob/core.py)
- [Official SDK headers and URL construction](https://github.com/vercel/vercel-py/blob/main/src/vercel/_internal/blob/__init__.py)

No functional or provider tests were run for this change.
