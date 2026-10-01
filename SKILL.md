---
name: image-approval-queue
description: Add a local, persistent review queue to an image generation workflow. Discover each round's images, present previews with Approve, Reject, Clear, and a configurable independent mark, and preserve decisions across later rounds and variants. Use when someone asks to review, promote, or approve generated images.
---

# Image approval queue

This file is a complete specification. An AI can implement the queue using tools available on its local system. The bundled Python app is an optional ready-made implementation, not a prerequisite for understanding or adapting this skill. The queue itself never starts image generation unless the user separately asks for images.

## What people ask for

Examples: “Add a review queue to this image round,” “Let me approve these images,” or “Open my image queue.” A person should not need to create a manifest, name an ID, or know where review data is stored. Locate the images and set those pieces up. If several plausible image sets exist, use the conversation and nearby output files to identify the intended one; ask only if that remains genuinely ambiguous.

The user sees image previews with Approve, Reject, Clear, and an independent mark. Default the mark to “Promote” for general use. Use a contextual label such as “Mark as cover” only when the work calls for it. Explain the controls in the interface: Clear removes the rating; Promote is separate from approval. Previously saved choices should appear when the queue reopens.

## Connect it to image rounds

When a round is completed, discover its actual output images, then add them to the queue automatically. The image generator can be any tool or service; use paths, asset handles, or URLs that the local environment can preview reliably. Do not assume filenames identify decisions. Keep one queue per project unless the user requests a different scope. When a later round arrives, add its images to the existing queue and leave earlier ratings and marks intact. When an image is edited or regenerated, add the result as a new variant linked to its source; keep both versions and their separate decisions. Never assign a prior ID to changed image content.

If generation and review happen in the same task, open or refresh the queue after each round, with new unrated images easy to find. If the user requests review of already existing images, create the queue from those images without generating replacements. Missing or inaccessible previews must be visibly reported rather than silently omitted.

## Required behavior

- Display a preview, stable identifier, useful name if available, round, and variant relation for each image. Support a full-size view and a narrow side panel.
- Provide Approve, Reject, and Clear as mutually exclusive rating actions. Each image starts unrated. Clear returns the image to unrated.
- Provide one independent Promote control with a configurable human label. It starts off, can be toggled, and does not change the rating. Multiple images can be promoted unless the user explicitly requests a single promotion.
- Save every click immediately. Confirm success in the UI only after durable storage succeeds. On failure, keep the prior displayed value and show the error.
- Retain an append-only timestamped event for every action, including Clear and removing promotion. Keep current state available for quick downstream use. Never erase a history entry when a choice changes.
- Preserve decisions when reopening, reordering, relabeling, adding a round, or adding a variant. Do not reset an existing ledger. Keep decisions for temporarily removed images so they reappear if the same ID returns.
- Make unrated images easy to find, with round and rating filters. A filter must not prevent a newly saved choice from appearing elsewhere later.
- Treat review decisions as user choices. A generator's plan, prompt, filename, or metadata must not preapprove or mark an image. Downstream use should read saved user decisions.

The UI can be a local browser page, app panel, or equivalent interactive surface supported by the environment. Prefer a local tool that requires no account or external hosting. Reuse an existing implementation only when it meets these behaviors. Otherwise, create one suited to the host. For Codex, the bundled `scripts/add_images.py`, `scripts/queue.py`, and `assets/queue.html` are an implementation; the format and launch details are in [references/usage.md](references/usage.md). If only this SKILL.md is available, build from the contract below and validate it with actual local images.

## Portable data contract

The manifest is an internal inventory the AI creates and updates. It connects previewable images to stable IDs; the user need not edit it. A practical shape is:

```json
{
  "project": "sample-project",
  "promotion_label": "Promote",
  "images": [
    {"id": "r1-001", "path": "round-01/first.png", "name": "First study", "round": 1},
    {"id": "r2-001-v2", "path": "round-02/first-revised.png", "name": "First study, revised", "round": 2, "variant_of": "r1-001"}
  ]
}
```

`id` is immutable and unique within the project. `path` is an example of a preview source; another host may use an asset handle or URL. Resolve relative paths from the inventory file, and avoid silently reassigning an ID when a file changes. `promotion_label` is display text, not a new decision type. Keep output inventory and user decisions in separate files so rebuilding the inventory cannot overwrite choices. A practical ledger is:

```json
{
  "version": 1,
  "images": {
    "r1-001": {
      "status": "approved",
      "promoted": true,
      "updated_at": "2026-01-01T00:00:00Z",
      "history": [
        {"at": "2026-01-01T00:00:00Z", "field": "status", "value": "approved"},
        {"at": "2026-01-01T00:01:00Z", "field": "promoted", "value": true}
      ]
    }
  }
}
```

Ratings are `pending`, `approved`, or `rejected`; `promoted` is independent. When adapting an older implementation, migrate existing decisions without losing history. Write a complete ledger atomically, serialize competing writes, and reject corrupt existing data rather than replacing it. Bind a local server to loopback only and limit it to explicitly inventoried assets; prevent unrelated files from being served. Keep state scoped by project to avoid ID collisions between unrelated queues.

## Verification and limits

With a small existing image set, click all actions, reopen the interface, confirm the saved values and history, add a later round and a variant, and verify previous choices remain. Check a narrow layout and a failed save. Do not generate images merely to test the queue; use existing images or simple local placeholders. A static mockup or a page that requires manual export after each choice does not fulfill this skill.

Image regeneration with per-image steering is a future extension. Until explicitly implemented, do not show a working “Regenerate” control or claim that a queued image can be regenerated from this interface. If implemented later, require the user to initiate it, collect steering for that image, preserve the original, and register the result as a new variant after generation completes.
