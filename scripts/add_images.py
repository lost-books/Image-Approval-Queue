#!/usr/bin/env python3
"""Add an existing image round to a queue, preserving prior review state."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif', '.svg'}


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as image:
        for chunk in iter(lambda: image.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add_images(manifest, sources, round_name, variant_of=None, name=None, promotion_label=None):
    manifest = Path(manifest).resolve()
    if manifest.exists():
        data = json.loads(manifest.read_text())
        if not isinstance(data.get('images'), list):
            raise ValueError('Invalid manifest; refusing to overwrite')
    else:
        data = {'images': []}
    if promotion_label is not None:
        if not isinstance(promotion_label, str) or not promotion_label.strip():
            raise ValueError('Promotion label must be nonempty')
        data['promotion_label'] = promotion_label
    else:
        data.setdefault('promotion_label', 'Promote')
    existing = {item['id']: item for item in data['images']}
    if len(existing) != len(data['images']):
        raise ValueError('Duplicate IDs in existing manifest')
    if variant_of and (len(sources) != 1 or variant_of not in existing):
        raise ValueError('--variant-of requires one image and an existing source ID')
    if name and len(sources) != 1:
        raise ValueError('--name requires one image')
    assets = manifest.parent / 'review-assets'
    added = []
    for source in sources:
        source = Path(source).resolve()
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f'Unsupported or missing image: {source}')
        content_digest = digest_file(source)
        identity = hashlib.sha256((str(round_name) + '\0' + str(source) + '\0' + content_digest).encode()).hexdigest()[:16]
        image_id = 'img-' + identity
        if image_id in existing:
            continue
        assets.mkdir(parents=True, exist_ok=True)
        target = assets / (content_digest + source.suffix.lower())
        if not target.exists():
            fd, temporary = tempfile.mkstemp(prefix=target.name + '.', dir=assets)
            os.close(fd)
            try:
                shutil.copyfile(source, temporary)
                if digest_file(Path(temporary)) != content_digest:
                    raise RuntimeError(f'Image changed during import: {source}')
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        item = {'id': image_id, 'path': str(target.relative_to(manifest.parent)), 'name': name or source.stem.replace('-', ' ').replace('_', ' '), 'round': round_name}
        if variant_of:
            item['variant_of'] = variant_of
        data['images'].append(item)
        existing[image_id] = item
        added.append(item)
    if added or not manifest.exists() or promotion_label is not None:
        atomic_json(manifest, data)
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--round', required=True)
    parser.add_argument('--directory', type=Path, help='Recursively add supported images from this directory')
    parser.add_argument('--variant-of', help='Existing image ID; requires a single image')
    parser.add_argument('--name', help='Display name; requires a single image')
    parser.add_argument('--promotion-label', help='Button label, such as Promote or Mark as cover')
    parser.add_argument('images', nargs='*', type=Path)
    args = parser.parse_args()
    sources = list(args.images)
    if args.directory:
        if not args.directory.is_dir():
            parser.error('Directory does not exist')
        assets = (args.manifest.resolve().parent / 'review-assets').resolve()
        sources += sorted(path for path in args.directory.rglob('*') if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.resolve().is_relative_to(assets))
    if not sources:
        parser.error('Provide image paths or --directory')
    try:
        added = add_images(args.manifest, sources, args.round, args.variant_of, args.name, args.promotion_label)
    except (ValueError, RuntimeError, KeyError) as error:
        parser.error(str(error))
    print(f'Added {len(added)} image(s) to {args.manifest.resolve()}')
    for item in added:
        print(f"{item['id']}  {item['name']}")


if __name__ == '__main__':
    main()
