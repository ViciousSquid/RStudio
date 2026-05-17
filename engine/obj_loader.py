from typing import List, Tuple, Optional, Iterator
from engine.resource_manager import ResourceManager


class OBJLoader:
    """
    Wavefront OBJ/MTL loader that consumes line iterators from ResourceManager.
    Eliminates all direct filesystem dependencies.
    """
    
    def __init__(self):
        self.vertices: List[Tuple[float, float, float]] = []
        self.texcoords: List[Tuple[float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.faces: List[dict] = []
        self.materials: dict = {}
    
    def load_from_resource(self, obj_path: str) -> bool:
        """
        Load model from ResourceManager stream.
        Automatically resolves companion MTL files.
        """
        rm = ResourceManager()
        
        # Get line iterator from text asset
        text = rm.get_text_asset(obj_path)
        if text is None:
            print(f"[OBJLoader] Failed to load: {obj_path}")
            return False
        
        lines = text.splitlines()
        
        # Parse OBJ data
        current_material = None
        mtl_lib_name = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split()
            if not parts:
                continue
            
            keyword = parts[0]
            
            if keyword == 'v' and len(parts) >= 4:
                self.vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif keyword == 'vt' and len(parts) >= 3:
                self.texcoords.append((float(parts[1]), float(parts[2])))
            elif keyword == 'vn' and len(parts) >= 4:
                self.normals.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif keyword == 'f' and len(parts) >= 4:
                face = {'vertices': [], 'material': current_material}
                for fp in parts[1:]:
                    # Parse "v/vt/vn" format
                    indices = fp.split('/')
                    v_idx = int(indices[0]) - 1 if indices[0] else 0
                    vt_idx = int(indices[1]) - 1 if len(indices) > 1 and indices[1] else -1
                    vn_idx = int(indices[2]) - 1 if len(indices) > 2 and indices[2] else -1
                    face['vertices'].append((v_idx, vt_idx, vn_idx))
                self.faces.append(face)
            elif keyword == 'usemtl' and len(parts) > 1:
                current_material = parts[1]
            elif keyword == 'mtllib' and len(parts) > 1:
                mtl_lib_name = parts[1]
        
        # Load companion MTL if referenced
        if mtl_lib_name:
            self._load_mtl_from_resource(obj_path, mtl_lib_name)
        
        return True
    
    def _load_mtl_from_resource(self, obj_path: str, mtl_name: str) -> None:
        """Resolve MTL path relative to OBJ location and load via ResourceManager."""
        rm = ResourceManager()
        
        # Derive MTL path from OBJ directory
        obj_dir = '/'.join(obj_path.replace('\\', '/').split('/')[:-1])
        mtl_path = f"{obj_dir}/{mtl_name}" if obj_dir else mtl_name
        
        mtl_text = rm.get_text_asset(mtl_path)
        if mtl_text is None:
            print(f"[OBJLoader] MTL not found: {mtl_path}")
            return
        
        current_mtl = None
        for line in mtl_text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            parts = line.split()
            if not parts:
                continue
            
            keyword = parts[0]
            
            if keyword == 'newmtl' and len(parts) > 1:
                current_mtl = parts[1]
                self.materials[current_mtl] = {
                    'diffuse': (0.8, 0.8, 0.8),
                    'ambient': (0.2, 0.2, 0.2),
                    'specular': (0.0, 0.0, 0.0),
                    'texture': None
                }
            elif current_mtl:
                mtl = self.materials[current_mtl]
                if keyword == 'Kd' and len(parts) >= 4:
                    mtl['diffuse'] = (float(parts[1]), float(parts[2]), float(parts[3]))
                elif keyword == 'Ka' and len(parts) >= 4:
                    mtl['ambient'] = (float(parts[1]), float(parts[2]), float(parts[3]))
                elif keyword == 'Ks' and len(parts) >= 4:
                    mtl['specular'] = (float(parts[1]), float(parts[2]), float(parts[3]))
                elif keyword in ('map_Kd', 'map_Ka') and len(parts) > 1:
                    # Store relative texture path for later resolution
                    mtl['texture'] = parts[1]