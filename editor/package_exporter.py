import os
import json
import zipfile
import shutil
from pathlib import Path
from typing import Set, List, Dict, Optional, Tuple
from collections import deque

from PyQt5.QtWidgets import QProgressDialog, QMessageBox, QApplication
from PyQt5.QtCore import Qt


class PackageExporter:
    """
    Handles .fiopak creation: metadata collection, asset crawling,
    recursive map dependency resolution, and ZIP assembly.
    """
    
    # Asset path patterns to scan for in map JSON
    ASSET_KEYS = {
        'textures': ['textures', 'texture', 'texture_path', 'sprite_2d', 'custom_idle', 
                     'custom_shoot', 'custom_dead'],
        'models': ['model_path', 'mesh'],
        'sounds': ['sound_file', 'sound', 'audio']
    }
    
    def __init__(self, editor_state, root_dir: str):
        self.editor_state = editor_state
        self.root_dir = os.path.abspath(root_dir)
        self._discovered_maps: Set[str] = set()
        self._discovered_assets: Dict[str, Set[str]] = {
            'textures': set(),
            'models': set(),
            'sounds': set()
        }
        self.errors: List[str] = []
    
    def export(self, output_path, metadata, current_map_path, parent_widget=None):
        """Export the current project as a .fiopak zip."""
        import zipfile
        import json
        import os

        # ── 1. Collect ALL map dependencies recursively ──────────────────
        start_map = metadata.get('map_path')
        all_maps = set()
        if start_map and os.path.exists(start_map):
            all_maps = self._collect_map_dependencies(start_map)
        else:
            # Fallback: use the provided current_map_path (no longer relies on editor_state.file_path)
            if current_map_path and os.path.exists(current_map_path):
                all_maps.add(os.path.abspath(current_map_path))

        # ── 2. Gather referenced assets from ALL maps ────────────────────
        referenced_assets = set()

        for map_file in all_maps:
            try:
                with open(map_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception as e:
                self.errors.append(f"Could not read {map_file}: {e}")
                continue

            # Scan brushes for textures
            for brush in data.get('brushes', []):
                textures = brush.get('textures', {})
                for face, tex in textures.items():
                    if tex and isinstance(tex, str):
                        referenced_assets.add(tex)

            # Scan things for model paths, sprites, sounds, etc.
            for thing in data.get('things', []):
                if not isinstance(thing, dict):
                    continue
                props = thing.get('properties', {})
                # Use ASSET_KEYS so we catch custom_idle, custom_shoot,
                # custom_dead, sprite_2d, sound_file, texture_path, etc.
                for asset_keys in self.ASSET_KEYS.values():
                    for key in asset_keys:
                        val = props.get(key)
                        if val and isinstance(val, str):
                            referenced_assets.add(val)

        # ── 3. Build the .fiopak zip ──────────────────────────────
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:

                # --- Write metadata.json ---
                zf.writestr('metadata.json', json.dumps(metadata, indent=2))

                # --- Write every discovered map (preserving folder structure) ---
                for map_file in all_maps:
                    arcname = os.path.relpath(map_file, self.root_dir)
                    zf.write(map_file, arcname)

                # --- Write referenced assets (textures, models, sounds, etc.) ---
                assets_dir = os.path.join(self.root_dir, 'assets')
                for asset_name in referenced_assets:
                    # Try multiple locations: assets/textures, assets/models, etc.
                    candidates = []
                    if os.path.isabs(asset_name):
                        candidates.append(asset_name)
                    else:
                        for sub in ('textures', 'models', 'sounds', 'sprites', 'materials'):
                            candidates.append(os.path.join(assets_dir, sub, asset_name))
                        candidates.append(os.path.join(assets_dir, asset_name))

                    found = False
                    for src_path in candidates:
                        if os.path.isfile(src_path):
                            arcname = os.path.relpath(src_path, self.root_dir)
                            zf.write(src_path, arcname)
                            found = True
                            break

                    if not found:
                        self.errors.append(f"Missing asset: {asset_name}")

                # --- Write any extra package files (scripts, configs, etc.) ---
                # (Add here if your engine needs specific files bundled)

        except Exception as e:
            self.errors.append(f"Failed to create package: {e}")
            return False, self.errors

        # ── 4. Report results ────────────────────────────────────────────
        if self.errors:
            # Warnings about missing assets, but package was still created
            return True, self.errors

        return True, []
    
    def _crawl_campaign(self, start_map_path: str) -> None:
        """
        Breadth-first crawl of all maps reachable via LevelChanger entities.
        Populates self._discovered_maps and self._discovered_assets.
        """
        queue = deque([start_map_path])
        
        while queue:
            map_rel_path = queue.popleft()
            if map_rel_path in self._discovered_maps:
                continue
            
            self._discovered_maps.add(map_rel_path)
            
            # Load map JSON
            map_full_path = os.path.join(self.root_dir, map_rel_path)
            if not os.path.exists(map_full_path):
                self.errors.append(f"Map file not found: {map_rel_path}")
                continue
            
            try:
                with open(map_full_path, 'r', encoding='utf-8') as f:
                    map_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.errors.append(f"Failed to parse {map_rel_path}: {e}")
                continue
            
            # Extract assets from this map
            self._extract_map_assets(map_data)
            
            # Find LevelChangers to discover next maps
            for thing in map_data.get('things', []):
                if thing.get('type') == 'LevelChanger':
                    target = thing.get('properties', {}).get('target_map', '')
                    if target:
                        # Normalize to maps/ relative path
                        if not target.startswith('maps/'):
                            target = f"maps/{target}"
                        if not target.endswith('.json'):
                            target += '.json'
                        queue.append(target)


    def _collect_map_dependencies(self, map_path, collected=None):
        """Recursively find all .json map files referenced by entities."""
        import json
        import os

        if collected is None:
            collected = set()

        abs_path = os.path.abspath(map_path)
        if abs_path in collected or not os.path.isfile(abs_path):
            return collected

        collected.add(abs_path)

        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.errors.append(f"Could not scan {map_path}: {e}")
            return collected

        # Entities may be stored in 'things' or 'brushes'
        all_entities = data.get('things', []) + data.get('brushes', [])

        for entity in all_entities:
            if not isinstance(entity, dict):
                continue

            # Merge top-level keys with nested 'properties' dict
            props = dict(entity)
            if 'properties' in entity and isinstance(entity['properties'], dict):
                props.update(entity['properties'])

            # Look for any property that references another map
            target_map = None
            for key in ('target_map', 'map', 'next_map', 'next_level',
                        'target_level', 'level_name', 'map_name'):
                if key in props and isinstance(props[key], str):
                    val = props[key].strip()
                    if val:
                        target_map = val
                        break

            if not target_map:
                continue

            # Resolve relative map path to absolute
            candidates = []
            if os.path.isabs(target_map):
                candidates.append(target_map)
            else:
                candidates.extend([
                    os.path.join(self.root_dir, 'maps', target_map),
                    os.path.join(self.root_dir, target_map),
                    os.path.join(os.path.dirname(abs_path), target_map),
                ])

            for candidate in candidates:
                if os.path.isfile(candidate):
                    self._collect_map_dependencies(candidate, collected)
                    break
            else:
                self.errors.append(
                    f"Missing dependency: map '{target_map}' "
                    f"referenced in {os.path.basename(abs_path)}"
                )

        return collected
    
    def _extract_map_assets(self, map_data: dict) -> None:
        """Scan map data structure for all asset references."""
        def scan_value(value, context: str = ''):
            if isinstance(value, dict):
                for k, v in value.items():
                    # Check if this key matches known asset patterns
                    for asset_type, keys in self.ASSET_KEYS.items():
                        if k in keys and isinstance(v, str) and v:
                            self._discovered_assets[asset_type].add(v)
                    # Recurse into nested structures
                    scan_value(v, f"{context}.{k}")
            elif isinstance(value, list):
                for item in value:
                    scan_value(item, context)
            elif isinstance(value, str) and value:
                # Heuristic: catch file extensions in string values
                lower = value.lower()
                if any(lower.endswith(ext) for ext in ['.png', '.jpg', '.tga', '.bmp']):
                    self._discovered_assets['textures'].add(value)
                elif lower.endswith('.obj'):
                    self._discovered_assets['models'].add(value)
                elif any(lower.endswith(ext) for ext in ['.wav', '.ogg', '.mp3']):
                    self._discovered_assets['sounds'].add(value)
        
        scan_value(map_data)
    
    def _resolve_asset_paths(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        Convert discovered relative paths to (archive_path, filesystem_path) tuples.
        Returns organized dict for ZIP assembly.
        """
        manifest = {'maps': [], 'assets': {'textures': [], 'models': [], 'sounds': []}}
        
        # Maps
        for map_rel in sorted(self._discovered_maps):
            # Safety: ensure map path is relative, never absolute
            clean_map_rel = map_rel.replace("\\", "/")
            if os.path.isabs(clean_map_rel):
                clean_map_rel = os.path.relpath(clean_map_rel, self.root_dir)
                clean_map_rel = clean_map_rel.replace("\\", "/")
            full = os.path.join(self.root_dir, clean_map_rel)
            if os.path.exists(full):
                manifest['maps'].append((clean_map_rel, full))
        
        # Assets by type
        for asset_type, paths in self._discovered_assets.items():
            for rel_path in sorted(paths):
                # Normalize path to assets/ subdirectory
                clean_path = rel_path.replace('\\', '/').lstrip('/')
                if not clean_path.startswith('assets/'):
                    archive_path = f"assets/{asset_type}/{os.path.basename(clean_path)}"
                else:
                    archive_path = clean_path
                
                full_path = os.path.join(self.root_dir, clean_path)
                if not os.path.exists(full_path):
                    # Try alternative resolution
                    alt_path = os.path.join(self.root_dir, archive_path)
                    if os.path.exists(alt_path):
                        full_path = alt_path
                    else:
                        self.errors.append(f"Asset not found: {rel_path}")
                        continue
                
                manifest['assets'][asset_type].append((archive_path, full_path))
        
        return manifest
    
    def _assemble_package(self, output_path: str, metadata: dict,
                         asset_manifest: dict, progress: QProgressDialog) -> bool:
        """Build the final ZIP archive with all contents."""
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Write manifest
                manifest_json = json.dumps(metadata, indent=2, ensure_ascii=False)
                zf.writestr('manifest.json', manifest_json)
                
                total_items = (len(asset_manifest['maps']) + 
                              sum(len(v) for v in asset_manifest['assets'].values()))
                processed = 0
                
                # Write maps
                for archive_path, fs_path in asset_manifest['maps']:
                    zf.write(fs_path, archive_path)
                    processed += 1
                    if processed % 5 == 0:
                        progress.setValue(50 + int(40 * processed / max(total_items, 1)))
                        QApplication.processEvents()
                
                # Write assets
                for asset_type, items in asset_manifest['assets'].items():
                    for archive_path, fs_path in items:
                        zf.write(fs_path, archive_path)
                        processed += 1
                
                # Copy banner if specified
                banner_src = metadata.get('banner_source_path', '')
                if banner_src and os.path.exists(banner_src):
                    banner_ext = os.path.splitext(banner_src)[1]
                    zf.write(banner_src, f"assets/package_banner{banner_ext}")
            
            return True
            
        except (IOError, OSError, zipfile.BadZipFile) as e:
            self.errors.append(f"Package assembly failed: {e}")
            return False