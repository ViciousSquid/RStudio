import os 
import numpy as np 
import ctypes
from PyQt5.QtWidgets import QMessageBox 
from OpenGL.GL import *

class OBJ: 
    """ Loads a .obj file, parses vertices, normals, and texture coordinates, and creates a modern OpenGL VAO for rendering. """
def init(self, filename): 
    self.vao = None 
    self.vbo = None 
    self.vertex_count = 0 
    self.is_loaded = False 
    self.filename = filename 
    self.load(filename)

def load(self, filename):
    if not os.path.exists(filename):
        print(f"Error: OBJ file not found at '{filename}'")
        return
    
    positions = []
    texcoords = []
    normals = []
    
    # Temporary storage for face indices
    # format: (pos_idx, tex_idx, norm_idx)
    faces = []

    try:
        with open(filename, "r") as f:
            for line in f:
                if line.startswith('#'): continue
                values = line.split()
                if not values: continue
                
                if values[0] == 'v':
                    positions.append(list(map(float, values[1:4])))
                elif values[0] == 'vt':
                    texcoords.append(list(map(float, values[1:3])))
                elif values[0] == 'vn':
                    normals.append(list(map(float, values[1:4])))
                elif values[0] == 'f':
                    # Triangulate simple polygons (fan triangulation)
                    # v1, v2, v3, v4 -> (v1,v2,v3), (v1,v3,v4)
                    face_verts = []
                    for v in values[1:]:
                        w = v.split('/')
                        # OBJ indices are 1-based
                        p_idx = int(w[0]) - 1 if w[0] else -1
                        t_idx = int(w[1]) - 1 if len(w) > 1 and w[1] else -1
                        n_idx = int(w[2]) - 1 if len(w) > 2 and w[2] else -1
                        face_verts.append((p_idx, t_idx, n_idx))
                    
                    for i in range(1, len(face_verts) - 1):
                        faces.append(face_verts[0])
                        faces.append(face_verts[i])
                        faces.append(face_verts[i+1])

        if not positions or not faces:
            print(f"Warning: No geometry found in {os.path.basename(filename)}")
            return

        # Center and Scale logic (Optional: Normalize to unit size)
        # Keeping original scale logic from previous version for consistency
        np_pos = np.array(positions)
        min_coord = np.min(np_pos, axis=0)
        max_coord = np.max(np_pos, axis=0)
        center = (min_coord + max_coord) / 2.0
        
        # Interleave data: [PosX, PosY, PosZ, NormX, NormY, NormZ, U, V]
        interleaved_data = []
        
        for p_idx, t_idx, n_idx in faces:
            # Position
            pos = np_pos[p_idx] - center
            interleaved_data.extend(pos)
            
            # Normal
            if n_idx != -1 and n_idx < len(normals):
                interleaved_data.extend(normals[n_idx])
            else:
                interleaved_data.extend([0, 1, 0]) # Default normal
            
            # TexCoord
            if t_idx != -1 and t_idx < len(texcoords):
                # Flip V coordinate for OpenGL
                interleaved_data.extend([texcoords[t_idx][0], 1.0 - texcoords[t_idx][1]])
            else:
                interleaved_data.extend([0.0, 0.0])

        vertex_data = np.array(interleaved_data, dtype=np.float32)
        self.vertex_count = len(faces)
        
        # --- Generate OpenGL Buffers ---
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        
        self.vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, vertex_data.nbytes, vertex_data, GL_STATIC_DRAW)
        
        stride = 8 * 4 # 8 floats * 4 bytes
        
        # Position (Loc 0, 3 floats, offset 0)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        
        # Normal (Loc 1, 3 floats, offset 12)
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        
        # Texture (Loc 2, 2 floats, offset 24)
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(24))
        
        glBindVertexArray(0)
        self.is_loaded = True
        print(f"Loaded OBJ: {filename} with {self.vertex_count//3} tris")

    except Exception as e:
        print(f"Error loading OBJ {filename}: {e}")
        self.is_loaded = False

def cleanup(self):
    if self.vao: glDeleteVertexArrays(1, [self.vao])
    if self.vbo: glDeleteBuffers(1, [self.vbo])