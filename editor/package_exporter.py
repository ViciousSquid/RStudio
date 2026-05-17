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
    Handles .gamepackage creation: metadata collection, asset crawling,
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
        self._errors: List[str] = []
    
    def export(self, output_path: str, metadata: dict, 
               progress_parent=None) -> Tuple[bool, List[str]]:
        """
        Execute full export pipeline.
        
        Args:
            output_path: Destination .gamepackage file path
            metadata: Dict from PackageMetadataDialog (title, author, etc.)
            progress_parent: QWidget for progress dialog parenting
            
        Returns:
            (success: bool, error_messages: list)
        """
        # Phase 1: Recursive asset crawling
        progress = QProgressDialog("Analyzing campaign structure...", "Cancel", 0, 100, progress_parent)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(5)
        QApplication.processEvents()
        
        start_map = metadata.get('start_map', 'maps/level_1.json')

        # Normalize start_map to a relative path within root_dir
        # start_map may be an absolute filesystem path (from self.file_path)
        # but the package expects paths relative to root_dir like 'maps/level_1.json'
        if os.path.isabs(start_map):
            # Convert absolute path to relative path under root_dir
            start_map = os.path.relpath(start_map, self.root_dir)
        # Ensure forward slashes for ZIP consistency
        start_map = start_map.replace("\\", "/")

        # CRITICAL: Update metadata so manifest.json gets the relative path too
        metadata['start_map'] = start_map

        self._crawl_campaign(start_map)
        
        if progress.wasCanceled():
            return False, ["Export cancelled by user."]
        
        progress.setValue(30)
        progress.setLabelText("Collecting asset dependencies...")
        QApplication.processEvents()
        
        # Phase 2: Resolve all asset paths to absolute filesystem locations
        asset_manifest = self._resolve_asset_paths()
        
        progress.setValue(50)
        progress.setLabelText("Building package archive...")
        QApplication.processEvents()
        
        # Phase 3: Assemble ZIP with manifest and all assets
        success = self._assemble_package(output_path, metadata, asset_manifest, progress)
        
        progress.setValue(100)
        
        if success and not self._errors:
            return True, []
        return success, self._errors
    
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
                self._errors.append(f"Map file not found: {map_rel_path}")
                continue
            
            try:
                with open(map_full_path, 'r', encoding='utf-8') as f:
                    map_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self._errors.append(f"Failed to parse {map_rel_path}: {e}")
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
                        self._errors.append(f"Asset not found: {rel_path}")
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
            self._errors.append(f"Package assembly failed: {e}")
            return False