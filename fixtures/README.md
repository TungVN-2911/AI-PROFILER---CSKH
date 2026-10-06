# Fixtures

All profiles here are **synthetic personas** (`"synthetic": true`). Names, organisations, posts and numeric ids
are fictional and were written for testing; they do not describe real people and were not collected from Facebook.
The `fixture.*` usernames and the `profile.php?id=` number are placeholders; the agent never contacts Facebook for
them unless `--live` is passed explicitly.

The agent looks up `fixtures/profiles/*.json` by canonical `facebook_url` (configurable via `PROFILE_STORE_DIR`), so
each URL below can be run directly:

```bash
python main.py --url "https://www.facebook.com/fixture.minh.anh"
```

| File | URL | Scenario | Expected result |
|---|---|---|---|
| `minh_anh.json` | `https://www.facebook.com/fixture.minh.anh` | Rich public profile: bio, work, education, 3 interests, city, 3 posts, avatar description | `SUCCESS`, 10 messages, `MÔ TẢ ẢNH (từ dữ liệu được cung cấp)`, gender/age `UNKNOWN` |
| `no_image_quoc_bao.json` | `https://www.facebook.com/fixture.quoc.bao` | Rich public profile without any image | `PARTIAL_OR_PRIVATE`, `NO_IMAGE:` (brief §4: no image collected) |
| `declared_khanh_linh.json` | `https://www.facebook.com/fixture.khanh.linh` | Self-declared gender, pronouns and birth year | `SUCCESS`, gender/age derived and labelled with fact ids; messages use "chị" / "em" |
| `profile_id_variant.json` | `https://www.facebook.com/profile.php?id=100000000000042` | Numeric `profile.php?id=` URL form | `SUCCESS` |
| `partial_thu_ha.json` | `https://www.facebook.com/fixture.thu.ha` | `PARTIAL` access: name + bio + avatar description only (exactly 2 usable facts) | `SUCCESS` with a shorter sequence (7 messages) |
| `name_only.json` | `https://www.facebook.com/fixture.name.only` | Public but only the display name | `PARTIAL_OR_PRIVATE`, `INSUFFICIENT_DATA:` |
| `private_user.json` | `https://www.facebook.com/fixture.private.user` | Private profile | `PARTIAL_OR_PRIVATE`, `PRIVATE_PROFILE:` |
| `dead_link.json` | `https://www.facebook.com/fixture.dead.link` | Removed account / dead link | `PARTIAL_OR_PRIVATE`, `NOT_FOUND:` |

Any URL without a fixture (and without `--profile-file` / `--live`) returns `PARTIAL_OR_PRIVATE` with a
`TECHNICAL LIMITATION:` note.

## Format

See `architecture.md` §4.1. Every field except `facebook_url` is optional; missing or blank fields are recorded as
`UNKNOWN` and never filled in. Unknown keys are rejected. `access.state` (`PUBLIC`, `PARTIAL`, `PRIVATE`,
`LOGIN_REQUIRED`, `NOT_FOUND`, `UNREACHABLE`) lets a fixture represent restricted or dead profiles without network
access; profile fields are ignored unless the state is `PUBLIC` or `PARTIAL`.
