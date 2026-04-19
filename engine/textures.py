import OpenGL.GL as gl                    # FIX#9: no wildcard import
from PyQt5.QtGui import QImage


class TextureManager:
    def __init__(self):
        self.textures = {}

    def get(self, path):
        if path not in self.textures:
            self.textures[path] = self._load_texture(path)
        return self.textures[path]

    def _load_texture(self, path):
        image = QImage(path)
        if image.isNull():
            print(f"Error loading image: {path}")
            return -1

        image = image.convertToFormat(QImage.Format_RGBA8888)
        width, height = image.width(), image.height()

        # FIX#10: Use constBits + sizeInBytes (Qt 5.10+) with fallback
        ptr = image.constBits()
        try:
            nbytes = image.sizeInBytes()
        except AttributeError:
            nbytes = image.byteCount()
        data = ptr.asstring(nbytes)

        texture_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width, height, 0,
                     gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)

        # Generate mipmaps, then set trilinear min filter + linear mag filter.
        # (generateMipmap must happen AFTER texImage2D; MAG_FILTER must not be a
        # mipmap filter — only MIN_FILTER supports mipmap variants.)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)

        # Anisotropic filtering (if supported by the GL implementation).
        # Uses the EXT_texture_filter_anisotropic enum values directly so this
        # works on drivers that expose the extension without our needing the
        # OpenGL.GL.EXT.texture_filter_anisotropic bindings.
        try:
            max_aniso = gl.glGetFloatv(0x84FF)  # GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT
            gl.glTexParameterf(gl.GL_TEXTURE_2D, 0x84FE, max_aniso)  # GL_TEXTURE_MAX_ANISOTROPY_EXT
        except Exception:
            pass

        return texture_id


# Instantiate a global texture manager
texture_manager = TextureManager()
