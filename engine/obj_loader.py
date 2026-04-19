import os
import numpy as np
import ctypes
import OpenGL.GL as gl   # FIX#9: no wildcard import


class OBJ:
    """ Loads a .obj file, parses vertices, normals, texcoords, and materials. """
    def __init__(self, filename):
        self.vao = None
        self.vbo = None
        self.vertex_count = 0
        self.is_loaded = False
        self.filename = filename
        self.cpu_vertices = []

        # Materials data: {'mat_name': {'color': [r,g,b], 'texture': 'path.png'}}
        self.materials = {}

        # Rendering groups: [{'material': 'mat_name', 'start': 0, 'count': 0}, ...]
        self.groups = []

        self.load(filename)

    def load(self, filename):
        if not os.path.exists(filename):
            print(f"Error: OBJ file not found at '{filename}'")
            return

        positions = []
        texcoords = []
        normals = []
        faces = []

        # Temporary storage to track material groups during parsing
        current_material = "default"
        # Stores {'material', 'count'} for each material section
        raw_groups = []
        face_counter = 0
        # Running total of triangles assigned to finalised groups so we don't
        # have to sum() over raw_groups each time usemtl is encountered
        # (avoids O(n^2) parsing on models with many materials).
        faces_in_prev_groups = 0

        model_dir = os.path.dirname(filename)

        try:
            with open(filename, "r") as f:
                for line in f:
                    if line.startswith('#'):
                        continue
                    values = line.split()
                    if not values:
                        continue

                    if values[0] == 'v':
                        positions.append(list(map(float, values[1:4])))
                    elif values[0] == 'vt':
                        texcoords.append(list(map(float, values[1:3])))
                    elif values[0] == 'vn':
                        normals.append(list(map(float, values[1:4])))

                    elif values[0] == 'usemtl':
                        mat_name = values[1]
                        # If we have emitted faces for the current material since
                        # the last usemtl, finalise that group before switching.
                        new_faces = face_counter - faces_in_prev_groups
                        if new_faces > 0:
                            raw_groups.append({'material': current_material,
                                               'count': new_faces})
                            faces_in_prev_groups = face_counter
                        current_material = mat_name

                    elif values[0] == 'f':
                        face_verts = []
                        for v in values[1:]:
                            w = v.split('/')
                            p_idx = int(w[0]) - 1 if w[0] else -1
                            t_idx = int(w[1]) - 1 if len(w) > 1 and w[1] else -1
                            n_idx = int(w[2]) - 1 if len(w) > 2 and w[2] else -1
                            face_verts.append((p_idx, t_idx, n_idx))

                        # Triangulate
                        for i in range(1, len(face_verts) - 1):
                            faces.append(face_verts[0])
                            faces.append(face_verts[i])
                            faces.append(face_verts[i + 1])
                            face_counter += 1

                    elif values[0] == 'mtllib':
                        mtl_filename = " ".join(values[1:])
                        self._load_mtl(mtl_filename, model_dir)

            if not positions or not faces:
                print(f"Warning: No geometry found in {os.path.basename(filename)}")
                return

            # Finalise the last group
            if face_counter > faces_in_prev_groups:
                raw_groups.append({
                    'material': current_material,
                    'count': face_counter - faces_in_prev_groups,
                })

            # Calculate actual start indices for OpenGL (vertex count = face count * 3)
            current_start = 0
            for grp in raw_groups:
                vert_count = grp['count'] * 3
                if vert_count > 0:
                    self.groups.append({
                        'material': grp['material'],
                        'start': current_start,
                        'count': vert_count,
                    })
                    current_start += vert_count

            # Normalize geometry (center it)
            np_pos = np.array(positions)
            min_coord = np.min(np_pos, axis=0)
            max_coord = np.max(np_pos, axis=0)
            center = (min_coord + max_coord) / 2.0

            interleaved_data = []
            self.cpu_vertices = []

            # Build the interleaved vertex buffer
            for p_idx, t_idx, n_idx in faces:
                # Position
                pos = np_pos[p_idx] - center
                interleaved_data.extend(pos)
                self.cpu_vertices.append(pos)

                # Normal
                if n_idx != -1 and n_idx < len(normals):
                    interleaved_data.extend(normals[n_idx])
                else:
                    interleaved_data.extend([0, 1, 0])

                # TexCoord
                if t_idx != -1 and t_idx < len(texcoords):
                    interleaved_data.extend([texcoords[t_idx][0], 1.0 - texcoords[t_idx][1]])
                else:
                    interleaved_data.extend([0.0, 0.0])

            vertex_data = np.array(interleaved_data, dtype=np.float32)
            # `faces` already holds one entry per triangle vertex (3 per triangle
            # after triangulation), so len(faces) *is* the vertex count.
            # The previous code multiplied by 3 here which produced a value 3x
            # too large and caused glDrawArrays to read past the buffer.
            self.vertex_count = len(faces)

            # OpenGL Setup
            self.vao = gl.glGenVertexArrays(1)
            gl.glBindVertexArray(self.vao)

            self.vbo = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, vertex_data.nbytes, vertex_data, gl.GL_STATIC_DRAW)

            stride = 8 * 4
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(1)
            gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(12))
            gl.glEnableVertexAttribArray(2)
            gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(24))

            gl.glBindVertexArray(0)
            self.is_loaded = True
            print(f"Loaded OBJ: {filename} ({self.vertex_count} vertices, {len(self.groups)} material groups)")

        except Exception as e:
            print(f"Error loading OBJ {filename}: {e}")
            import traceback
            traceback.print_exc()
            self.is_loaded = False

    def _load_mtl(self, mtl_filename, model_dir):
        path = os.path.join(model_dir, mtl_filename)
        if not os.path.exists(path):
            path = os.path.join('assets', 'models', mtl_filename)

        if os.path.exists(path):
            current_mtl = None
            try:
                with open(path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue

                        parts = line.split()

                        if parts[0] == 'newmtl':
                            current_mtl = parts[1]
                            self.materials[current_mtl] = {'color': [0.8, 0.8, 0.8], 'texture': None}

                        elif parts[0] == 'Kd' and current_mtl:
                            # Parse Diffuse Color (RGB)
                            self.materials[current_mtl]['color'] = [float(parts[1]), float(parts[2]), float(parts[3])]

                        elif parts[0] == 'map_Kd' and current_mtl:
                            # Parse Texture Map
                            self.materials[current_mtl]['texture'] = os.path.basename(" ".join(parts[1:]))
            except Exception as e:
                print(f"Failed to parse MTL {path}: {e}")

    def cleanup(self):
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
        if self.vbo:
            gl.glDeleteBuffers(1, [self.vbo])
