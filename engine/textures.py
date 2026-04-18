from OpenGL.GL import *
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
        data = image.bits().asstring(image.byteCount())

        texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, data)

        # Generate mipmaps, then set trilinear min filter + linear mag filter.
        # (generateMipmap must happen AFTER texImage2D; MAG_FILTER must not be a
        # mipmap filter — only MIN_FILTER supports mipmap variants.)
        glGenerateMipmap(GL_TEXTURE_2D)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

        # Anisotropic filtering (if supported by the GL implementation).
        # Uses the EXT_texture_filter_anisotropic enum values directly so this
        # works on drivers that expose the extension without our needing the
        # OpenGL.GL.EXT.texture_filter_anisotropic bindings.
        try:
            max_aniso = glGetFloatv(0x84FF)  # GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT
            glTexParameterf(GL_TEXTURE_2D, 0x84FE, max_aniso)  # GL_TEXTURE_MAX_ANISOTROPY_EXT
        except Exception:
            pass

        return texture_id


# Instantiate a global texture manager
texture_manager = TextureManager()
