import os

def load_shader_from_file(filepath):
    """Loads a shader from a file and returns its content as a string."""
    try:
        with open(filepath, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"FATAL: Shader file not found: {filepath}")
        return "" # Return empty string on error
    except Exception as e:
        print(f"FATAL: Error reading shader file {filepath}: {e}")
        return ""

# --- Define paths to shader files ---
shader_dir = os.path.join(os.path.dirname(__file__), 'shaders')

# --- Load all shaders from their individual files ---
VERTEX_SHADER_SIMPLE = load_shader_from_file(os.path.join(shader_dir, 'vertex_shader_simple.glsl'))
FRAGMENT_SHADER_SIMPLE = load_shader_from_file(os.path.join(shader_dir, 'fragment_shader_simple.glsl'))

VERTEX_SHADER_LIT = load_shader_from_file(os.path.join(shader_dir, 'vertex_shader_lit.glsl'))
FRAGMENT_SHADER_LIT = load_shader_from_file(os.path.join(shader_dir, 'fragment_shader_lit.glsl'))

VERTEX_SHADER_TEXTURED = load_shader_from_file(os.path.join(shader_dir, 'vertex_shader_textured.glsl'))
FRAGMENT_SHADER_TEXTURED = load_shader_from_file(os.path.join(shader_dir, 'fragment_shader_textured.glsl'))

VERTEX_SHADER_SPRITE = load_shader_from_file(os.path.join(shader_dir, 'vertex_shader_sprite.glsl'))
FRAGMENT_SHADER_SPRITE = load_shader_from_file(os.path.join(shader_dir, 'fragment_shader_sprite.glsl'))

SHADOW_VOLUME_VERTEX_SHADER = load_shader_from_file(os.path.join(shader_dir, 'shadow_volume_vertex_shader.glsl'))
SHADOW_VOLUME_FRAGMENT_SHADER = load_shader_from_file(os.path.join(shader_dir, 'shadow_volume_fragment_shader.glsl'))

VERTEX_SHADER_FOG = load_shader_from_file(os.path.join(shader_dir, 'vertex_shader_fog.glsl'))
FRAGMENT_SHADER_FOG = load_shader_from_file(os.path.join(shader_dir, 'fragment_shader_fog.glsl'))

# --- Procedural Material Shaders ---
VERTEX_SHADER_PROCEDURAL = load_shader_from_file(os.path.join(shader_dir, 'procedural_vert.glsl'))
FRAGMENT_SHADER_PROCEDURAL = load_shader_from_file(os.path.join(shader_dir, 'procedural_frag.glsl'))

# Material type mapping for procedural shader
PROCEDURAL_MATERIAL_TYPES = {
    'Default': 0,
    'Metal': 1,
    'Glass': 2,
    'Concrete': 3,
    'Brick': 4,
    'Wood': 5,
    'Marble': 6,
    'Rust': 7,
    'Glow': 8,
    'Water': 9,
}
