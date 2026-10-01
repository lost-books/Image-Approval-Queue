# Using the bundled app

The skill can be followed on its own to build a local queue. This folder also includes a ready-made Python implementation for macOS and Linux, requiring Python 3.9+ and no extra packages. Copy the folder into `~/.codex/skills/` to install it for Codex. The user can simply ask Codex to add a review queue to an image round; the AI should locate and import the images.

For direct use, add an existing round, then launch the queue:

```sh
python3 scripts/add_images.py --manifest /path/to/project/review/manifest.json --round 1 --directory /path/to/project/round-01
python3 scripts/queue.py --manifest /path/to/project/review/manifest.json
```

The importer finds supported images in the directory and creates the internal manifest and immutable preview copies. It prints IDs for later variant links. Repeating the same import adds nothing; importing another round adds its images without resetting decisions. A single revised image can be linked to its original:

```sh
python3 scripts/add_images.py --manifest /path/to/project/review/manifest.json --round 2 --variant-of img-original-id /path/to/revised.png
```

Use `--promotion-label 'Mark as cover'` on an import when that wording helps the review purpose. Otherwise the control reads **Promote**. The label affects only the interface; ratings and promotion remain independent. A promotion can be toggled off with **Remove promotion**. Clear affects only the rating.

The queue prints a localhost URL. Keep its process running during review. Codex can open that URL in its right-side browser panel with `open_in_codex`. `--port 8765` requests a fixed port. `--decisions /path/to/decisions.json` selects an existing or alternate decision file. The default is `manifest.decisions.json` beside the manifest.

A zero-cost sample uses the included SVG shapes:

```sh
python3 scripts/queue.py --manifest examples/manifest.json
```

# Internal data format

The AI normally creates this file. Humans do not need to edit it. A manifest is an inventory of previewable images:

```json
{
  "promotion_label": "Promote",
  "images": [
    {"id": "round-1-a", "path": "round-01/a.png", "name": "First study", "round": 1},
    {"id": "round-2-a-v2", "path": "round-02/a-v2.png", "name": "Revised study", "round": 2, "variant_of": "round-1-a"}
  ]
}
```

`id` and `path` are required. IDs are stable and unique within the queue. Paths can be absolute or relative to the manifest file. Optional `name`, `round`, `variant`, and `variant_of` provide display context. Extra source metadata is ignored and is never treated as a review choice. Previews support PNG, JPEG, WebP, GIF, AVIF, and SVG. The importer copies images into `review-assets/` so a source file overwritten by a later generation does not silently replace the reviewed image. These copied assets belong to the user's project queue, not to the skill package.

A separate ledger records user choices:

```json
{
  "version": 1,
  "images": {
    "round-1-a": {
      "status": "approved",
      "promoted": true,
      "updated_at": "2026-01-01T00:00:00+00:00",
      "history": [
        {"at": "2026-01-01T00:00:00+00:00", "field": "status", "value": "approved", "before": {"status": "pending", "promoted": false}},
        {"at": "2026-01-01T00:01:00+00:00", "field": "promoted", "value": true, "before": {"status": "approved", "promoted": false}}
      ]
    }
  }
}
```

Unrecorded images are pending and unpromoted. Every click adds a timestamped history event, including Clear and Remove promotion. Writes are serialized, flushed, and atomically replaced before the UI reports success. A process lock prevents two queue servers from writing the same ledger at once. Invalid existing state causes an error rather than resetting choices. Removed image IDs remain in the ledger and resume their decisions if added back.

Older ledgers with `marked_cover` are read as promoted. Their original fields and history remain untouched. On the next user save, a `promoted` field is written; later promotion changes take precedence over the legacy value. Pass an older ledger explicitly with `--decisions` if its filename differs from the default. The importer never edits a decision ledger.

The browser page has round and decision filters, full-size image links, history, and Refresh. The server binds only to localhost, serves only inventoried images, and requires a session token for writes. It does not use an external image service. A missing preview and a failed save are shown visibly.

# Verification

```sh
python3 -m unittest discover -s tests -v
```

Tests cover HTTP decisions, persistence, legacy state, validation, rounds, variants, and snapshot imports. The sample page is also suitable for a browser check without image generation.
