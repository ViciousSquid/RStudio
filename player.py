# player.py — Standalone game launcher for .gamepackage files

import sys
import os
import json
import argparse
import pygame
import glm
import numpy as np
from pathlib import Path

# Ensure engine modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.resource_manager import ResourceManager
from engine.threaded_game_state import ThreadedGameState
from engine.renderer import Renderer  # Assuming exists
from engine.camera import Camera


class PackagePlayer:
    """
    Standalone launcher that mounts a .gamepackage and boots directly into gameplay.
    Bypasses editor UI entirely — presents splash/dashboard then launches game loop.
    """
    
    def __init__(self, package_path: str):
        self.package_path = os.path.abspath(package_path)
        self.rm = ResourceManager()
        self.screen: Optional[pygame.display.Surface] = None
        self.clock = pygame.time.Clock()
        
    def run(self):
        """Main entry: mount package, show splash, launch game."""
        # Initialize pygame
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        
        # Mount package
        if not self.rm.mount_package(self.package_path):
            print(f"Failed to mount package: {self.package_path}")
            sys.exit(1)
        
        manifest = self.rm.get_manifest()
        if not manifest:
            print("Invalid package: no manifest found")
            sys.exit(1)
        
        # Create window
        self.screen = pygame.display.set_mode((1280, 720), pygame.DOUBLEBUF)
        pygame.display.set_caption(f"{manifest.get('title', 'Fio Game')}")
        
        # Show splash/dashboard
        if not self._show_splash_dashboard(manifest):
            return  # User quit during splash
        
        # Launch game loop
        try:
            self._launch_gameplay(manifest)
        except Exception as e:
            import traceback
            print(f"[Player] FATAL ERROR: {e}")
            traceback.print_exc()
            pygame.quit()
            raise
    
    def _show_splash_dashboard(self, manifest: dict) -> bool:
        """
        Display package info, banner, and "Press START to Play" prompt.
        Returns False if user quits, True to proceed.
        """
        # Load banner if available
        banner_surface = None
        banner_path = manifest.get('banner')
        if banner_path:
            banner_bytes = self.rm.get_asset(banner_path)
            if banner_bytes:
                try:
                    from io import BytesIO
                    banner_surface = pygame.image.load(BytesIO(banner_bytes))
                    banner_surface = pygame.transform.smoothscale(banner_surface, (640, 360))
                except pygame.error:
                    pass
        
        # Fonts
        title_font = pygame.font.SysFont("Segoe UI", 48, bold=True)
        info_font = pygame.font.SysFont("Segoe UI", 24)
        prompt_font = pygame.font.SysFont("Segoe UI", 32, bold=True)
        
        title = manifest.get('title', 'Untitled')
        author = manifest.get('author', 'Unknown Author')
        description = manifest.get('description', '')
        
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        waiting = False
                    if event.key == pygame.K_ESCAPE:
                        return False
            
            # Render dashboard
            self.screen.fill((20, 20, 30))
            
            # Banner
            if banner_surface:
                bx = (self.screen.get_width() - banner_surface.get_width()) // 2
                self.screen.blit(banner_surface, (bx, 40))
                y_offset = 420
            else:
                y_offset = 120
            
            # Title
            title_surf = title_font.render(title, True, (255, 200, 100))
            tx = (self.screen.get_width() - title_surf.get_width()) // 2
            self.screen.blit(title_surf, (tx, y_offset))
            
            # Author
            author_surf = info_font.render(f"by {author}", True, (180, 180, 180))
            ax = (self.screen.get_width() - author_surf.get_width()) // 2
            self.screen.blit(author_surf, (ax, y_offset + 60))
            
            # Description (wrapped)
            desc_lines = self._wrap_text(description, info_font, self.screen.get_width() - 200)
            for i, line in enumerate(desc_lines[:4]):  # Max 4 lines
                ds = info_font.render(line, True, (200, 200, 200))
                dx = (self.screen.get_width() - ds.get_width()) // 2
                self.screen.blit(ds, (dx, y_offset + 110 + i * 30))
            
            # Prompt
            prompt = prompt_font.render("Press ENTER to Start", True, (100, 255, 100))
            px = (self.screen.get_width() - prompt.get_width()) // 2
            self.screen.blit(prompt, (px, self.screen.get_height() - 80))
            
            pygame.display.flip()
            self.clock.tick(60)
        
        return True
    
    def _wrap_text(self, text: str, font, max_width: int) -> list[str]:
        """Simple text wrapper for pygame font rendering."""
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines
    
    def _launch_gameplay(self, manifest: dict):
        """Initialize engine state and enter game loop."""
        start_map = manifest.get('start_map', 'maps/level_1.json')

        print(f"[Player] Loading map: {start_map}")

        # Load starting map from package
        map_data = self.rm.get_text_asset(start_map)
        if map_data is None:
            print(f"[Player] Failed to load start map: {start_map}")
            return

        try:
            level_data = json.loads(map_data)
        except json.JSONDecodeError as e:
            print(f"[Player] Failed to parse map JSON: {e}")
            return

        print(f"[Player] Map loaded: {len(level_data.get('brushes', []))} brushes, {len(level_data.get('things', []))} things")

        # Find player start position from things list
        player_start_pos = [0, 64, 0]  # Default fallback
        player_start_angle = 0
        for thing in level_data.get('things', []):
            if thing.get('type') == 'PlayerStart':
                player_start_pos = thing.get('pos', [0, 64, 0])
                player_start_angle = thing.get('properties', {}).get('angle', 0)
                break

        print(f"[Player] Player start: {player_start_pos}, angle: {player_start_angle}")

        try:
            # Create a simple game state that mimics what the renderer expects
            game_state = SimpleGameState(level_data)
            print("[Player] GameState created")

            # Texture loader callback for the renderer
            def load_texture(name, subfolder):
                return self.rm.get_texture(name, subfolder)

            # Initialize renderer
            print("[Player] Initializing renderer...")
            renderer = Renderer(load_texture, 16, 2048)
            renderer.resource_manager = self.rm
            print("[Player] Renderer initialized")

            # Camera setup
            camera = Camera()
            camera.pos = glm.vec3(*player_start_pos)
            camera.yaw = player_start_angle
            print("[Player] Camera ready")

            # Main game loop
            print("[Player] Entering game loop...")
            running = True
            frame_count = 0
            while running:
                dt = self.clock.tick(60) / 1000.0

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        running = False

                # Update
                game_state.update(dt)

                # Render
                renderer.clear()
                renderer.render_scene(game_state, camera)
                pygame.display.flip()

                frame_count += 1
                if frame_count % 60 == 0:
                    print(f"[Player] Frame {frame_count}, dt={dt:.4f}")

            print(f"[Player] Game loop ended after {frame_count} frames")
            pygame.quit()
        except Exception as e:
            import traceback
            print(f"[Player] ERROR in game loop: {e}")
            traceback.print_exc()
            pygame.quit()
            raise


class SimpleGameState:
    """Minimal game state for standalone play mode."""
    def __init__(self, level_data: dict):
        self.brushes = level_data.get('brushes', [])
        self.things = level_data.get('things', [])
        self.player_pos = glm.vec3(0, 64, 0)
        self.player_angle = 0.0
        self.player_pitch = 0.0
        self.player_health = 100
        self.player_max_health = 100
        self.player_dead = False
        self.active_weapon = None
        self.collected_keys = set()
        self.hud_message = ""
        self.bullet_marks = []
        self.projectiles = []
        self.muzzle_flash_active = False
        self.monster_debug_active = False
        self.monster_debug_rays = []

    def update(self, dt):
        """Minimal update - placeholder for gameplay logic."""
        pass

    def get_player_start_position(self):
        """Return player start position for camera setup."""
        return self.player_pos

def main():
    parser = argparse.ArgumentParser(description="Fio Game Package Player")
    parser.add_argument("package", help="Path to .gamepackage file")
    args = parser.parse_args()
    
    if not os.path.exists(args.package):
        print(f"Package not found: {args.package}")
        sys.exit(1)
    
    player = PackagePlayer(args.package)
    player.run()


if __name__ == "__main__":
    main()